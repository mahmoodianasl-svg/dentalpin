from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.patient_agent.handoff_staff_service import StaffHandoffService
from app.modules.patient_agent.models import PatientAgentAuditEvent, PatientAgentSession


def _handoff_session(
    *,
    clinic_id,
    patient_id=None,
    state: str = "requested",
    urgency: str = "urgent",
    summary: str = "Patient requests human assistance.",
) -> PatientAgentSession:
    return PatientAgentSession(
        clinic_id=clinic_id,
        patient_id=patient_id,
        channel="voice",
        status="active",
        authenticated=True,
        handoff_state=state,
        context={"handoff_urgency": urgency, "handoff_summary": summary},
    )


@pytest.mark.asyncio
async def test_staff_handoff_queue_is_clinic_scoped_and_pending_only(
    db_session: AsyncSession,
    test_clinic: Clinic,
) -> None:
    other_clinic = Clinic(
        id=uuid4(),
        name="Other Clinic",
        tax_id=f"T-{uuid4().hex[:8]}",
        address={"street": "Other St", "city": "Madrid"},
        settings={"slot_duration_min": 15},
    )
    emergency = _handoff_session(
        clinic_id=test_clinic.id,
        state="emergency_escalation",
        urgency="emergency_escalation",
        summary="Patient reports an emergency-risk signal.",
    )
    routine = _handoff_session(clinic_id=test_clinic.id, state="requested", urgency="routine")
    accepted = _handoff_session(clinic_id=test_clinic.id, state="accepted")
    no_handoff = PatientAgentSession(
        clinic_id=test_clinic.id,
        channel="text",
        status="active",
        authenticated=True,
        handoff_state="none",
    )
    foreign = _handoff_session(clinic_id=other_clinic.id, state="emergency_escalation")
    db_session.add_all([other_clinic, emergency, routine, accepted, no_handoff, foreign])
    await db_session.commit()

    queued = await StaffHandoffService().list_pending(db=db_session, clinic_id=test_clinic.id)

    assert [session.id for session in queued] == [emergency.id, routine.id]
    assert queued[0].context["handoff_summary"] == "Patient reports an emergency-risk signal."


@pytest.mark.asyncio
async def test_staff_accept_handoff_is_audited_and_preserves_patient_context(
    db_session: AsyncSession,
    test_clinic: Clinic,
) -> None:
    actor_user_id = uuid4()
    session = _handoff_session(
        clinic_id=test_clinic.id,
        state="emergency_escalation",
        urgency="emergency_escalation",
        summary="Patient requests immediate human assistance.",
    )
    db_session.add(session)
    await db_session.commit()

    accepted = await StaffHandoffService().accept(
        db=db_session,
        clinic_id=test_clinic.id,
        session_id=session.id,
        actor_user_id=actor_user_id,
    )
    await db_session.commit()

    assert accepted.handoff_state == "accepted"
    assert accepted.context["handoff_summary"] == "Patient requests immediate human assistance."
    assert accepted.context["handoff_urgency"] == "emergency_escalation"
    assert accepted.context["handoff_accepted_by"] == str(actor_user_id)
    assert accepted.context["handoff_accepted_at"]

    audit = (
        await db_session.execute(
            select(PatientAgentAuditEvent).where(
                PatientAgentAuditEvent.session_id == session.id,
                PatientAgentAuditEvent.event_type == "patient_handoff_accepted",
            )
        )
    ).scalar_one()
    assert audit.actor_type == "staff"
    assert audit.outcome == "success"
    assert audit.detail["actor_user_id"] == str(actor_user_id)
    assert audit.detail["previous_handoff_state"] == "emergency_escalation"
    assert audit.detail["handoff_urgency"] == "emergency_escalation"


@pytest.mark.asyncio
async def test_staff_accept_handoff_rejects_second_claim(
    db_session: AsyncSession,
    test_clinic: Clinic,
) -> None:
    session = _handoff_session(clinic_id=test_clinic.id)
    db_session.add(session)
    await db_session.commit()

    service = StaffHandoffService()
    await service.accept(
        db=db_session,
        clinic_id=test_clinic.id,
        session_id=session.id,
        actor_user_id=uuid4(),
    )
    await db_session.commit()

    with pytest.raises(ValueError, match="already been accepted"):
        await service.accept(
            db=db_session,
            clinic_id=test_clinic.id,
            session_id=session.id,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_staff_handoff_lookup_and_accept_are_clinic_scoped(
    db_session: AsyncSession,
    test_clinic: Clinic,
) -> None:
    other_clinic = Clinic(
        id=uuid4(),
        name="Scoped Other Clinic",
        tax_id=f"T-{uuid4().hex[:8]}",
        address={"street": "Other St", "city": "Madrid"},
        settings={"slot_duration_min": 15},
    )
    session = _handoff_session(clinic_id=other_clinic.id)
    db_session.add_all([other_clinic, session])
    await db_session.commit()

    service = StaffHandoffService()
    assert (
        await service.get_handoff(
            db=db_session,
            clinic_id=test_clinic.id,
            session_id=session.id,
        )
        is None
    )
    with pytest.raises(LookupError, match="not found"):
        await service.accept(
            db=db_session,
            clinic_id=test_clinic.id,
            session_id=session.id,
            actor_user_id=uuid4(),
        )
