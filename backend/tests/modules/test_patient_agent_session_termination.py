from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.patient_agent.identity import PatientPrincipal
from app.modules.patient_agent.models import PatientAgentAuditEvent, PatientAgentSession
from app.modules.patient_agent.providers.base import (
    RealtimeAIProvider,
    RealtimeSessionDescriptor,
    RealtimeSessionRequest,
)
from app.modules.patient_agent.service import PatientAgentService
from app.modules.patients.models import Patient


class RecordingRealtimeProvider(RealtimeAIProvider):
    name = "test-provider"

    def __init__(self, *, fail_close: bool = False) -> None:
        self.fail_close = fail_close
        self.closed_refs: list[str] = []

    async def create_session(self, request: RealtimeSessionRequest) -> RealtimeSessionDescriptor:
        return RealtimeSessionDescriptor(
            provider=self.name,
            provider_session_ref=f"provider-{request.session_id}",
            client_secret="ephemeral-test-secret",
            expires_at_epoch=2_000_000_000,
        )

    async def close_session(self, provider_session_ref: str) -> None:
        self.closed_refs.append(provider_session_ref)
        if self.fail_close:
            raise RuntimeError("provider close failed")


def _principal(*, clinic_id, patient_id) -> PatientPrincipal:  # noqa: ANN001
    return PatientPrincipal(
        patient_id=patient_id,
        clinic_id=clinic_id,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


async def _active_session(
    *,
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> PatientAgentSession:
    session = PatientAgentSession(
        clinic_id=test_clinic.id,
        patient_id=test_patient.id,
        channel="voice",
        status="active",
        authenticated=True,
        provider="test-provider",
        provider_session_ref="provider-session-ref",
    )
    db_session.add(session)
    await db_session.commit()
    return session


@pytest.mark.asyncio
async def test_end_session_is_idempotent_and_audited_once(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    session = await _active_session(
        db_session=db_session,
        test_clinic=test_clinic,
        test_patient=test_patient,
    )
    provider = RecordingRealtimeProvider()
    service = PatientAgentService(provider)
    principal = _principal(clinic_id=test_clinic.id, patient_id=test_patient.id)

    first_ended_at = await service.end_session(
        db=db_session,
        principal=principal,
        session=session,
    )
    await db_session.commit()
    second_ended_at = await service.end_session(
        db=db_session,
        principal=principal,
        session=session,
    )
    await db_session.commit()

    assert session.status == "ended"
    assert session.ended_at == first_ended_at
    assert second_ended_at == first_ended_at
    assert provider.closed_refs == ["provider-session-ref"]

    audit_count = (
        await db_session.execute(
            select(func.count(PatientAgentAuditEvent.id)).where(
                PatientAgentAuditEvent.session_id == session.id,
                PatientAgentAuditEvent.event_type == "realtime_session_ended",
            )
        )
    ).scalar_one()
    assert audit_count == 1

    audit = (
        await db_session.execute(
            select(PatientAgentAuditEvent).where(
                PatientAgentAuditEvent.session_id == session.id,
                PatientAgentAuditEvent.event_type == "realtime_session_ended",
            )
        )
    ).scalar_one()
    assert audit.outcome == "success"
    assert audit.detail == {
        "channel": "voice",
        "provider": "test-provider",
        "provider_close_succeeded": True,
    }


@pytest.mark.asyncio
async def test_end_session_remains_authoritative_when_provider_close_fails(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    session = await _active_session(
        db_session=db_session,
        test_clinic=test_clinic,
        test_patient=test_patient,
    )
    provider = RecordingRealtimeProvider(fail_close=True)
    service = PatientAgentService(provider)

    ended_at = await service.end_session(
        db=db_session,
        principal=_principal(clinic_id=test_clinic.id, patient_id=test_patient.id),
        session=session,
    )
    await db_session.commit()

    assert session.status == "ended"
    assert session.ended_at == ended_at
    assert provider.closed_refs == ["provider-session-ref"]
    audit = (
        await db_session.execute(
            select(PatientAgentAuditEvent).where(
                PatientAgentAuditEvent.session_id == session.id,
                PatientAgentAuditEvent.event_type == "realtime_session_ended",
            )
        )
    ).scalar_one()
    assert audit.detail["provider_close_succeeded"] is False


@pytest.mark.asyncio
async def test_ended_session_cannot_authorize_visual_snapshot(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    session = await _active_session(
        db_session=db_session,
        test_clinic=test_clinic,
        test_patient=test_patient,
    )
    provider = RecordingRealtimeProvider()
    service = PatientAgentService(provider)
    principal = _principal(clinic_id=test_clinic.id, patient_id=test_patient.id)

    await service.end_session(db=db_session, principal=principal, session=session)
    await db_session.commit()

    with pytest.raises(ValueError, match="active realtime voice session"):
        await service.authorize_visual_snapshot_share(
            db=db_session,
            principal=principal,
            session=session,
            mime_type="image/png",
            size_bytes=1024,
        )
