from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.patient_agent.identity import PatientPrincipal
from app.modules.patient_agent.models import PatientAgentSession
from app.modules.patient_agent.router import request_patient_handoff
from app.modules.patient_agent.schemas import HumanHandoffRequest
from app.modules.patients.models import Patient


def _principal(*, clinic_id, patient_id) -> PatientPrincipal:  # noqa: ANN001
    return PatientPrincipal(
        patient_id=patient_id,
        clinic_id=clinic_id,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


@pytest.mark.asyncio
async def test_handoff_response_preserves_emergency_escalation_state(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    session = PatientAgentSession(
        clinic_id=test_clinic.id,
        patient_id=test_patient.id,
        channel="voice",
        status="active",
        authenticated=True,
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    response = await request_patient_handoff(
        session_id=session.id,
        payload=HumanHandoffRequest(
            reason="Patient requests immediate human assistance.",
            urgency="emergency_escalation",
        ),
        principal=_principal(clinic_id=test_clinic.id, patient_id=test_patient.id),
        db=db_session,
    )

    assert response.data["handoff_state"] == "emergency_escalation"
    assert session.handoff_state == "emergency_escalation"
    assert session.context["handoff_summary"] == "Patient requests immediate human assistance."
    assert session.context["handoff_urgency"] == "emergency_escalation"
