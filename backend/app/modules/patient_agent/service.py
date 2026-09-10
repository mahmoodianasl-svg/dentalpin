"""Realtime patient-agent session orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from time import monotonic
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .dental_conversation import IntakeSignal, classify_intake_risk
from .identity import PatientPrincipal
from .models import PatientAgentAuditEvent, PatientAgentConsent, PatientAgentSession
from .providers.base import RealtimeAIProvider, RealtimeSessionRequest
from .runtime_controls import (
    enforce_realtime_session_start_limit,
    enforce_visual_snapshot_share_limit,
)
from .safety import AgentRiskLevel, highest_risk_level


class PatientAgentService:
    def __init__(self, provider: RealtimeAIProvider) -> None:
        self.provider = provider

    async def start_session(
        self,
        *,
        db: AsyncSession,
        principal: PatientPrincipal,
        channel: str,
        locale: str | None,
        ai_consent: bool,
        audio_consent: bool,
        video_consent: bool,
    ) -> tuple[PatientAgentSession, str | None, int | None]:
        required = {
            "text": ai_consent,
            "voice": ai_consent and audio_consent,
        }
        if channel not in required:
            raise ValueError("Unsupported patient-agent channel")
        if not required[channel]:
            raise ValueError("Required patient consent has not been granted")

        await enforce_realtime_session_start_limit(db=db, principal=principal)

        session = PatientAgentSession(
            id=uuid4(),
            clinic_id=principal.clinic_id,
            patient_id=principal.patient_id,
            channel=channel,
            status="creating",
            locale=locale,
            authenticated=True,
        )
        db.add(session)
        await db.flush()

        consents: list[tuple[str, bool, dict[str, object]]] = [
            ("ai", ai_consent, {"source": "patient_session"})
        ]
        if channel == "voice":
            consents.append(("audio", audio_consent, {"source": "patient_session"}))
            consents.append(
                (
                    "video",
                    video_consent,
                    {
                        "source": "patient_session",
                        "scope": "visual_snapshot_only",
                        "continuous_video": False,
                    },
                )
            )
        for consent_type, granted, evidence in consents:
            db.add(
                PatientAgentConsent(
                    session_id=session.id,
                    clinic_id=principal.clinic_id,
                    patient_id=principal.patient_id,
                    consent_type=consent_type,
                    granted=granted,
                    policy_version="patient-agent-safety-v1",
                    evidence=evidence,
                )
            )

        modalities = ("text",) if channel == "text" else ("audio", "text")
        provider_started_at = monotonic()
        try:
            descriptor = await self.provider.create_session(
                RealtimeSessionRequest(
                    session_id=str(session.id),
                    channel=channel,
                    locale=locale,
                    modalities=modalities,
                )
            )
        except Exception as exc:
            provider_latency_ms = max(0, int((monotonic() - provider_started_at) * 1000))
            session.status = "failed"
            db.add(
                PatientAgentAuditEvent(
                    session_id=session.id,
                    clinic_id=principal.clinic_id,
                    patient_id=principal.patient_id,
                    event_type="realtime_session_failed",
                    actor_type="system",
                    outcome="failure",
                    detail={
                        "channel": channel,
                        "provider_error": type(exc).__name__,
                        "provider_latency_ms": provider_latency_ms,
                    },
                    reason="Realtime provider session could not be created",
                )
            )
            await db.commit()
            raise RuntimeError("Realtime provider session failed") from exc

        provider_latency_ms = max(0, int((monotonic() - provider_started_at) * 1000))
        session.status = "active"
        session.provider = descriptor.provider
        session.provider_session_ref = descriptor.provider_session_ref
        db.add(
            PatientAgentAuditEvent(
                session_id=session.id,
                clinic_id=principal.clinic_id,
                patient_id=principal.patient_id,
                event_type="realtime_session_started",
                actor_type="patient",
                outcome="success",
                detail={
                    "channel": channel,
                    "provider": descriptor.provider,
                    "provider_latency_ms": provider_latency_ms,
                },
            )
        )
        return session, descriptor.client_secret, descriptor.expires_at_epoch

    async def end_session(
        self,
        *,
        db: AsyncSession,
        principal: PatientPrincipal,
        session: PatientAgentSession,
    ) -> datetime:
        if session.clinic_id != principal.clinic_id or session.patient_id != principal.patient_id:
            raise PermissionError("Patient session scope mismatch")
        if session.status == "ended" and session.ended_at is not None:
            return session.ended_at

        ended_at = datetime.now(UTC)
        provider_close_succeeded = True
        if session.provider_session_ref:
            try:
                await self.provider.close_session(session.provider_session_ref)
            except Exception:
                provider_close_succeeded = False

        session.status = "ended"
        session.ended_at = ended_at
        db.add(
            PatientAgentAuditEvent(
                session_id=session.id,
                clinic_id=principal.clinic_id,
                patient_id=principal.patient_id,
                event_type="realtime_session_ended",
                actor_type="patient",
                outcome="success",
                detail={
                    "channel": session.channel,
                    "provider": session.provider,
                    "provider_close_succeeded": provider_close_succeeded,
                },
                reason="Patient ended realtime session",
            )
        )
        await db.flush()
        return ended_at

    async def revoke_visual_snapshot_consent(
        self,
        *,
        db: AsyncSession,
        principal: PatientPrincipal,
        session: PatientAgentSession,
    ) -> None:
        if session.clinic_id != principal.clinic_id or session.patient_id != principal.patient_id:
            raise PermissionError("Patient session scope mismatch")
        if session.channel != "voice" or session.status != "active":
            raise ValueError(
                "Visual snapshot consent can only change during an active voice session"
            )

        latest_consent = (
            await db.execute(
                select(PatientAgentConsent)
                .where(
                    PatientAgentConsent.session_id == session.id,
                    PatientAgentConsent.clinic_id == principal.clinic_id,
                    PatientAgentConsent.patient_id == principal.patient_id,
                    PatientAgentConsent.consent_type == "video",
                )
                .order_by(PatientAgentConsent.created_at.desc(), PatientAgentConsent.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if latest_consent is not None and latest_consent.granted is False:
            return

        db.add(
            PatientAgentConsent(
                session_id=session.id,
                clinic_id=principal.clinic_id,
                patient_id=principal.patient_id,
                consent_type="video",
                granted=False,
                policy_version="patient-agent-safety-v1",
                evidence={
                    "source": "patient_session",
                    "scope": "visual_snapshot_only",
                    "continuous_video": False,
                    "revoked_mid_session": True,
                },
            )
        )
        db.add(
            PatientAgentAuditEvent(
                session_id=session.id,
                clinic_id=principal.clinic_id,
                patient_id=principal.patient_id,
                event_type="visual_snapshot_consent_revoked",
                actor_type="patient",
                outcome="recorded",
                detail={
                    "scope": "visual_snapshot_only",
                    "media_content_persisted": False,
                    "continuous_video": False,
                },
                reason="Patient revoked visual snapshot consent",
            )
        )
        await db.flush()

    async def authorize_visual_snapshot_share(
        self,
        *,
        db: AsyncSession,
        principal: PatientPrincipal,
        session: PatientAgentSession,
        mime_type: str,
        size_bytes: int,
    ) -> UUID:
        if session.clinic_id != principal.clinic_id or session.patient_id != principal.patient_id:
            raise PermissionError("Patient session scope mismatch")
        if session.channel != "voice" or session.status != "active":
            raise ValueError("Visual snapshots require an active realtime voice session")

        consent = (
            await db.execute(
                select(PatientAgentConsent)
                .where(
                    PatientAgentConsent.session_id == session.id,
                    PatientAgentConsent.clinic_id == principal.clinic_id,
                    PatientAgentConsent.patient_id == principal.patient_id,
                    PatientAgentConsent.consent_type == "video",
                )
                .order_by(PatientAgentConsent.created_at.desc(), PatientAgentConsent.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if (
            consent is None
            or consent.granted is not True
            or consent.evidence.get("scope") != "visual_snapshot_only"
        ):
            db.add(
                PatientAgentAuditEvent(
                    session_id=session.id,
                    clinic_id=principal.clinic_id,
                    patient_id=principal.patient_id,
                    event_type="visual_snapshot_share_denied",
                    actor_type="patient",
                    outcome="denied",
                    detail={
                        "reason": "snapshot_consent_missing",
                        "mime_type": mime_type,
                        "size_bytes": size_bytes,
                        "scope": "visual_snapshot_only",
                        "media_content_persisted": False,
                        "continuous_video": False,
                    },
                    reason="Visual snapshot consent was not granted for this session",
                )
            )
            await db.commit()
            raise PermissionError("Visual snapshot consent was not granted for this session")

        await enforce_visual_snapshot_share_limit(
            db=db,
            principal=principal,
            session_id=session.id,
        )

        snapshot_id = uuid4()
        db.add(
            PatientAgentAuditEvent(
                session_id=session.id,
                clinic_id=principal.clinic_id,
                patient_id=principal.patient_id,
                event_type="visual_snapshot_share_authorized",
                actor_type="patient",
                outcome="authorized",
                detail={
                    "snapshot_id": str(snapshot_id),
                    "mime_type": mime_type,
                    "size_bytes": size_bytes,
                    "scope": "visual_snapshot_only",
                    "media_content_persisted": False,
                    "continuous_video": False,
                },
            )
        )
        await db.flush()
        return snapshot_id

    async def assess_intake_risk(
        self,
        *,
        db: AsyncSession,
        principal: PatientPrincipal,
        session: PatientAgentSession,
        reason: str,
        signals: frozenset[IntakeSignal],
    ) -> AgentRiskLevel:
        if session.clinic_id != principal.clinic_id or session.patient_id != principal.patient_id:
            raise PermissionError("Patient session scope mismatch")
        if session.status != "active":
            raise ValueError("Intake risk can only be assessed for an active session")

        assessed = classify_intake_risk(signals)
        context = dict(session.context or {})
        prior_value = context.get("intake_risk")
        prior = (
            AgentRiskLevel(prior_value)
            if prior_value in AgentRiskLevel._value2member_map_
            else AgentRiskLevel.ROUTINE
        )
        effective = highest_risk_level(prior, assessed)
        context["intake_risk"] = effective.value
        context["intake_signals"] = sorted(signal.value for signal in signals)
        session.context = context

        requires_handoff = effective in {
            AgentRiskLevel.URGENT,
            AgentRiskLevel.EMERGENCY_ESCALATION,
        }
        safety_decision = "continue"
        if effective == AgentRiskLevel.EMERGENCY_ESCALATION:
            safety_decision = "emergency_escalation"
        elif effective == AgentRiskLevel.URGENT:
            safety_decision = "human_handoff"

        db.add(
            PatientAgentAuditEvent(
                session_id=session.id,
                clinic_id=principal.clinic_id,
                patient_id=principal.patient_id,
                event_type="intake_risk_assessed",
                actor_type="system",
                outcome="recorded",
                detail={
                    "tool_name": "assess_patient_intake_risk",
                    "assessed_urgency": assessed.value,
                    "effective_urgency": effective.value,
                    "signals": sorted(signal.value for signal in signals),
                    "requires_handoff": requires_handoff,
                    "safety_decision": safety_decision,
                    "diagnostic": False,
                },
                reason="Deterministic intake risk classification",
            )
        )

        if requires_handoff:
            await self.request_handoff(
                db=db,
                principal=principal,
                session=session,
                reason=reason,
                actor_type="system",
            )
        else:
            await db.flush()
        return effective

    async def request_handoff(
        self,
        *,
        db: AsyncSession,
        principal: PatientPrincipal,
        session: PatientAgentSession,
        reason: str,
        urgency: AgentRiskLevel | None = None,
        actor_type: str = "patient",
    ) -> None:
        if session.clinic_id != principal.clinic_id or session.patient_id != principal.patient_id:
            raise PermissionError("Patient session scope mismatch")

        summary = reason.strip()
        context = dict(session.context or {})
        risk_value = context.get("intake_risk")
        server_urgency = (
            AgentRiskLevel(risk_value)
            if risk_value in AgentRiskLevel._value2member_map_
            else AgentRiskLevel.ROUTINE
        )
        effective_urgency = (
            highest_risk_level(server_urgency, urgency) if urgency is not None else server_urgency
        )
        urgency_source = "server_session"
        if urgency is not None and effective_urgency != server_urgency:
            urgency_source = "trusted_api_raise"

        context["handoff_summary"] = summary
        context["handoff_urgency"] = effective_urgency.value
        session.context = context
        session.handoff_state = (
            "emergency_escalation"
            if effective_urgency == AgentRiskLevel.EMERGENCY_ESCALATION
            else "requested"
        )
        db.add(
            PatientAgentAuditEvent(
                session_id=session.id,
                clinic_id=principal.clinic_id,
                patient_id=principal.patient_id,
                event_type=(
                    "emergency_escalation_requested"
                    if effective_urgency == AgentRiskLevel.EMERGENCY_ESCALATION
                    else "human_handoff_requested"
                ),
                actor_type=actor_type,
                outcome="recorded",
                detail={
                    "tool_name": "request_patient_human_handoff",
                    "urgency": effective_urgency.value,
                    "summary_preserved": True,
                    "server_derived_urgency": urgency_source == "server_session",
                    "urgency_source": urgency_source,
                    "safety_decision": session.handoff_state,
                },
                reason=(
                    "Emergency escalation requested"
                    if effective_urgency == AgentRiskLevel.EMERGENCY_ESCALATION
                    else "Human handoff requested"
                ),
            )
        )
        await db.flush()
