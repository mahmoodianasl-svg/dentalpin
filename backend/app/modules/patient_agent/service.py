"""Realtime patient-agent session orchestration."""

from __future__ import annotations

from time import monotonic
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .identity import PatientPrincipal
from .models import PatientAgentAuditEvent, PatientAgentConsent, PatientAgentSession
from .providers.base import RealtimeAIProvider, RealtimeSessionRequest
from .runtime_controls import (
    enforce_realtime_session_start_limit,
    enforce_visual_snapshot_share_limit,
)


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
                select(PatientAgentConsent).where(
                    PatientAgentConsent.session_id == session.id,
                    PatientAgentConsent.clinic_id == principal.clinic_id,
                    PatientAgentConsent.patient_id == principal.patient_id,
                    PatientAgentConsent.consent_type == "video",
                    PatientAgentConsent.granted.is_(True),
                )
            )
        ).scalar_one_or_none()
        if consent is None or consent.evidence.get("scope") != "visual_snapshot_only":
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

    async def request_handoff(
        self,
        *,
        db: AsyncSession,
        principal: PatientPrincipal,
        session: PatientAgentSession,
        reason: str,
        urgency: str,
    ) -> None:
        if session.clinic_id != principal.clinic_id or session.patient_id != principal.patient_id:
            raise PermissionError("Patient session scope mismatch")

        summary = reason.strip()
        context = dict(session.context or {})
        context["handoff_summary"] = summary
        context["handoff_urgency"] = urgency
        session.context = context
        session.handoff_state = (
            "emergency_escalation" if urgency == "emergency_escalation" else "requested"
        )
        db.add(
            PatientAgentAuditEvent(
                session_id=session.id,
                clinic_id=principal.clinic_id,
                patient_id=principal.patient_id,
                event_type=(
                    "emergency_escalation_requested"
                    if urgency == "emergency_escalation"
                    else "human_handoff_requested"
                ),
                actor_type="patient",
                outcome="recorded",
                detail={
                    "urgency": urgency,
                    "summary_preserved": True,
                },
                reason=summary,
            )
        )
