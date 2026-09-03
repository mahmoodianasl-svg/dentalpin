"""Realtime patient-agent session orchestration."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from .identity import PatientPrincipal
from .models import PatientAgentAuditEvent, PatientAgentConsent, PatientAgentSession
from .providers.base import RealtimeAIProvider, RealtimeSessionRequest


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
            "video": ai_consent and audio_consent and video_consent,
        }
        if channel not in required:
            raise ValueError("Unsupported patient-agent channel")
        if not required[channel]:
            raise ValueError("Required patient consent has not been granted")

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

        consents = [("ai", ai_consent)]
        if channel in {"voice", "video"}:
            consents.append(("audio", audio_consent))
        if channel == "video":
            consents.append(("video", video_consent))
        for consent_type, granted in consents:
            db.add(
                PatientAgentConsent(
                    session_id=session.id,
                    clinic_id=principal.clinic_id,
                    patient_id=principal.patient_id,
                    consent_type=consent_type,
                    granted=granted,
                    policy_version="patient-agent-safety-v1",
                    evidence={"source": "patient_session"},
                )
            )

        modalities = ("text",) if channel == "text" else ("audio", "text")
        descriptor = await self.provider.create_session(
            RealtimeSessionRequest(
                session_id=str(session.id),
                channel=channel,
                locale=locale,
                modalities=modalities,
            )
        )
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
                detail={"channel": channel, "provider": descriptor.provider},
            )
        )
        return session, descriptor.client_secret, descriptor.expires_at_epoch

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
        session.handoff_state = "requested"
        db.add(
            PatientAgentAuditEvent(
                session_id=session.id,
                clinic_id=principal.clinic_id,
                patient_id=principal.patient_id,
                event_type="human_handoff_requested",
                actor_type="patient",
                outcome="recorded",
                detail={"urgency": urgency},
                reason=reason,
            )
        )
