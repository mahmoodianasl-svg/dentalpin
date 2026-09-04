from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from jose import jwt
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth.models import Clinic, ClinicMembership
from app.modules.agenda.models import Appointment
from app.modules.agenda.service import AppointmentService
from app.modules.patient_agent.agenda_adapter import DentalPinPatientAppointmentAdapter
from app.modules.patient_agent.confirmation import (
    create_appointment_confirmation_token,
    decode_appointment_confirmation_token,
)
from app.modules.patient_agent.identity import PatientPrincipal
from app.modules.patient_agent.models import (
    PatientAgentAppointmentProposal,
    PatientAgentAuditEvent,
    PatientAgentSession,
)
from app.modules.patient_agent.providers.base import RealtimeAIProvider, RealtimeSessionRequest
from app.modules.patient_agent.router import request_patient_handoff
from app.modules.patient_agent.schemas import HumanHandoffRequest, RealtimeSessionCreate
from app.modules.patient_agent.service import PatientAgentService
from app.modules.patient_agent.tools import AppointmentSlot
from app.modules.patients.models import Patient
from app.modules.schedules.models import ClinicWeeklySchedule, ScheduleShift


class FailingRealtimeProvider(RealtimeAIProvider):
    name = "failing"

    async def create_session(self, request: RealtimeSessionRequest):  # noqa: ANN201
        del request
        raise RuntimeError("provider unavailable")

    async def close_session(self, provider_session_ref: str) -> None:
        del provider_session_ref


def _principal(*, clinic_id, patient_id) -> PatientPrincipal:  # noqa: ANN001
    return PatientPrincipal(
        patient_id=patient_id,
        clinic_id=clinic_id,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


async def _configure_open_monday(
    db_session: AsyncSession,
    test_clinic: Clinic,
) -> ClinicMembership:
    membership = (
        (
            await db_session.execute(
                select(ClinicMembership).where(ClinicMembership.clinic_id == test_clinic.id)
            )
        )
        .scalars()
        .first()
    )
    assert membership is not None
    membership.is_professional = True
    weekly = ClinicWeeklySchedule(clinic_id=test_clinic.id)
    weekly.shifts.append(
        ScheduleShift(
            weekday=0,
            shift_date=None,
            start_time=time(9, 0),
            end_time=time(17, 0),
        )
    )
    db_session.add(weekly)
    await db_session.commit()
    return membership


def test_ai1_schema_rejects_video_and_legacy_emergency() -> None:
    with pytest.raises(ValidationError):
        RealtimeSessionCreate(channel="video", ai_consent=True, audio_consent=True)
    with pytest.raises(ValidationError):
        HumanHandoffRequest(reason="urgent help", urgency="emergency")
    request = HumanHandoffRequest(reason="urgent help", urgency="emergency_escalation")
    assert request.urgency == "emergency_escalation"


@pytest.mark.asyncio
async def test_service_rejects_video_channel(db_session: AsyncSession) -> None:
    service = PatientAgentService(FailingRealtimeProvider())
    with pytest.raises(ValueError, match="Unsupported patient-agent channel"):
        await service.start_session(
            db=db_session,
            principal=_principal(clinic_id=uuid4(), patient_id=uuid4()),
            channel="video",
            locale="en",
            ai_consent=True,
            audio_consent=True,
            video_consent=True,
        )


@pytest.mark.asyncio
async def test_voice_requires_audio_consent(db_session: AsyncSession) -> None:
    service = PatientAgentService(FailingRealtimeProvider())
    with pytest.raises(ValueError, match="Required patient consent"):
        await service.start_session(
            db=db_session,
            principal=_principal(clinic_id=uuid4(), patient_id=uuid4()),
            channel="voice",
            locale="en",
            ai_consent=True,
            audio_consent=False,
            video_consent=False,
        )


@pytest.mark.asyncio
async def test_provider_failure_persists_failed_session_and_audit(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    service = PatientAgentService(FailingRealtimeProvider())
    principal = _principal(clinic_id=test_clinic.id, patient_id=test_patient.id)

    with pytest.raises(RuntimeError, match="Realtime provider session failed"):
        await service.start_session(
            db=db_session,
            principal=principal,
            channel="voice",
            locale="en",
            ai_consent=True,
            audio_consent=True,
            video_consent=False,
        )

    session = (
        await db_session.execute(
            select(PatientAgentSession).where(
                PatientAgentSession.clinic_id == test_clinic.id,
                PatientAgentSession.patient_id == test_patient.id,
            )
        )
    ).scalar_one()
    assert session.status == "failed"
    audit = (
        await db_session.execute(
            select(PatientAgentAuditEvent).where(
                PatientAgentAuditEvent.session_id == session.id,
                PatientAgentAuditEvent.event_type == "realtime_session_failed",
            )
        )
    ).scalar_one()
    assert audit.outcome == "failure"
    assert audit.detail["provider_error"] == "RuntimeError"


def test_confirmation_token_has_jti_and_rejects_tampering() -> None:
    clinic_id = uuid4()
    patient_id = uuid4()
    professional_id = uuid4()
    starts_at = datetime(2030, 1, 7, 9, 0, tzinfo=UTC)
    ends_at = starts_at + timedelta(minutes=30)
    token = create_appointment_confirmation_token(
        clinic_id=clinic_id,
        patient_id=patient_id,
        professional_id=professional_id,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    claims = decode_appointment_confirmation_token(
        token,
        clinic_id=clinic_id,
        patient_id=patient_id,
    )
    assert claims["jti"]

    header, payload, signature = token.split(".")
    replacement = "A" if signature[0] != "A" else "B"
    tampered = f"{header}.{payload}.{replacement}{signature[1:]}"
    with pytest.raises(ValueError, match="Invalid or expired confirmation token"):
        decode_appointment_confirmation_token(
            tampered,
            clinic_id=clinic_id,
            patient_id=patient_id,
        )


def test_confirmation_token_rejects_expiry() -> None:
    now = datetime.now(UTC)
    clinic_id = uuid4()
    patient_id = uuid4()
    token = jwt.encode(
        {
            "type": "patient_confirmation",
            "purpose": "patient_agent_appointment_confirmation",
            "jti": uuid4().hex,
            "clinic_id": str(clinic_id),
            "patient_id": str(patient_id),
            "professional_id": str(uuid4()),
            "starts_at": now.isoformat(),
            "ends_at": (now + timedelta(minutes=30)).isoformat(),
            "iat": now - timedelta(minutes=20),
            "exp": now - timedelta(minutes=10),
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    with pytest.raises(ValueError, match="Invalid or expired confirmation token"):
        decode_appointment_confirmation_token(
            token,
            clinic_id=clinic_id,
            patient_id=patient_id,
        )


@pytest.mark.asyncio
async def test_slot_validation_normalizes_clinic_time_and_rejects_outside_hours(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    membership = await _configure_open_monday(db_session, test_clinic)
    adapter = DentalPinPatientAppointmentAdapter(db_session)

    local_naive = AppointmentSlot(
        professional_id=membership.user_id,
        starts_at=datetime(2030, 1, 7, 10, 0),
        ends_at=datetime(2030, 1, 7, 10, 30),
    )
    normalized = await adapter.validate_slot_available(
        clinic_id=test_clinic.id,
        patient_id=test_patient.id,
        slot=local_naive,
    )
    assert normalized.starts_at == datetime(2030, 1, 7, 9, 0, tzinfo=UTC)

    outside = AppointmentSlot(
        professional_id=membership.user_id,
        starts_at=datetime(2030, 1, 7, 18, 0, tzinfo=UTC),
        ends_at=datetime(2030, 1, 7, 18, 30, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="outside available hours"):
        await adapter.validate_slot_available(
            clinic_id=test_clinic.id,
            patient_id=test_patient.id,
            slot=outside,
        )


@pytest.mark.asyncio
async def test_search_detects_overlap_that_starts_before_window(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    membership = await _configure_open_monday(db_session, test_clinic)
    db_session.add(
        Appointment(
            clinic_id=test_clinic.id,
            patient_id=test_patient.id,
            professional_id=membership.user_id,
            start_time=datetime(2030, 1, 7, 8, 30, tzinfo=UTC),
            end_time=datetime(2030, 1, 7, 9, 30, tzinfo=UTC),
            status="scheduled",
        )
    )
    await db_session.commit()

    adapter = DentalPinPatientAppointmentAdapter(db_session)
    slots = await adapter.search_available_slots(
        clinic_id=test_clinic.id,
        patient_id=test_patient.id,
        starts_after=datetime(2030, 1, 7, 9, 0, tzinfo=UTC),
        ends_before=datetime(2030, 1, 7, 10, 0, tzinfo=UTC),
        professional_id=membership.user_id,
    )
    assert [slot.starts_at for slot in slots] == [datetime(2030, 1, 7, 9, 30, tzinfo=UTC)]


@pytest.mark.asyncio
async def test_confirmation_rechecks_slot_and_preserves_unconsumed_proposal_on_conflict(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    membership = await _configure_open_monday(db_session, test_clinic)
    slot = AppointmentSlot(
        professional_id=membership.user_id,
        starts_at=datetime(2030, 1, 7, 11, 0, tzinfo=UTC),
        ends_at=datetime(2030, 1, 7, 11, 30, tzinfo=UTC),
    )
    token = create_appointment_confirmation_token(
        clinic_id=test_clinic.id,
        patient_id=test_patient.id,
        professional_id=slot.professional_id,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
    )
    claims = decode_appointment_confirmation_token(
        token,
        clinic_id=test_clinic.id,
        patient_id=test_patient.id,
    )
    proposal = PatientAgentAppointmentProposal(
        jti=claims["jti"],
        clinic_id=test_clinic.id,
        patient_id=test_patient.id,
        professional_id=slot.professional_id,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
        expires_at=datetime.fromtimestamp(int(claims["exp"]), tz=UTC),
    )
    db_session.add(proposal)
    db_session.add(
        Appointment(
            clinic_id=test_clinic.id,
            patient_id=test_patient.id,
            professional_id=membership.user_id,
            start_time=datetime(2030, 1, 7, 10, 45, tzinfo=UTC),
            end_time=datetime(2030, 1, 7, 11, 15, tzinfo=UTC),
            status="scheduled",
        )
    )
    await db_session.commit()

    adapter = DentalPinPatientAppointmentAdapter(db_session)
    with pytest.raises(ValueError, match="no longer available"):
        await adapter.create_appointment(
            clinic_id=test_clinic.id,
            patient_id=test_patient.id,
            slot=slot,
            confirmation_token=token,
        )
    await db_session.refresh(proposal)
    assert proposal.consumed_at is None


@pytest.mark.asyncio
async def test_confirmation_is_one_time_and_audited(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    membership = await _configure_open_monday(db_session, test_clinic)
    slot = AppointmentSlot(
        professional_id=membership.user_id,
        starts_at=datetime(2030, 1, 7, 12, 0, tzinfo=UTC),
        ends_at=datetime(2030, 1, 7, 12, 30, tzinfo=UTC),
    )
    token = create_appointment_confirmation_token(
        clinic_id=test_clinic.id,
        patient_id=test_patient.id,
        professional_id=slot.professional_id,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
    )
    claims = decode_appointment_confirmation_token(
        token,
        clinic_id=test_clinic.id,
        patient_id=test_patient.id,
    )
    proposal = PatientAgentAppointmentProposal(
        jti=claims["jti"],
        clinic_id=test_clinic.id,
        patient_id=test_patient.id,
        professional_id=slot.professional_id,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
        expires_at=datetime.fromtimestamp(int(claims["exp"]), tz=UTC),
    )
    db_session.add(proposal)
    await db_session.commit()

    async def commit_without_publishing(db: AsyncSession, appointment: Appointment) -> None:
        del appointment
        await db.commit()

    monkeypatch.setattr(
        AppointmentService,
        "commit_and_publish_scheduled",
        commit_without_publishing,
    )
    adapter = DentalPinPatientAppointmentAdapter(db_session)
    appointment_id = await adapter.create_appointment(
        clinic_id=test_clinic.id,
        patient_id=test_patient.id,
        slot=slot,
        confirmation_token=token,
    )
    assert appointment_id is not None

    with pytest.raises(ValueError, match="already been used"):
        await adapter.create_appointment(
            clinic_id=test_clinic.id,
            patient_id=test_patient.id,
            slot=slot,
            confirmation_token=token,
        )
    await db_session.refresh(proposal)
    assert proposal.consumed_at is not None
    audit = (
        await db_session.execute(
            select(PatientAgentAuditEvent).where(
                PatientAgentAuditEvent.event_type == "appointment_confirmation_consumed",
                PatientAgentAuditEvent.patient_id == test_patient.id,
            )
        )
    ).scalar_one()
    assert audit.detail["appointment_id"] == str(appointment_id)


@pytest.mark.asyncio
async def test_handoff_lookup_is_patient_scoped(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    session = PatientAgentSession(
        clinic_id=test_clinic.id,
        patient_id=uuid4(),
        channel="voice",
        status="active",
        authenticated=True,
    )
    db_session.add(session)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await request_patient_handoff(
            session_id=session.id,
            payload=HumanHandoffRequest(reason="help", urgency="urgent"),
            principal=_principal(clinic_id=test_clinic.id, patient_id=test_patient.id),
            db=db_session,
        )
    assert exc_info.value.status_code == 404
