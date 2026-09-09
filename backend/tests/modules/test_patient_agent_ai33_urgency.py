from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.patient_agent.dental_conversation import IntakeSignal
from app.modules.patient_agent.identity import PatientPrincipal
from app.modules.patient_agent.models import PatientAgentAuditEvent, PatientAgentSession
from app.modules.patient_agent.providers.base import RealtimeAIProvider, RealtimeSessionRequest
from app.modules.patient_agent.providers.openai_realtime import (
    PATIENT_HANDOFF_TOOL,
    PATIENT_INTAKE_RISK_TOOL,
)
from app.modules.patient_agent.safety import AgentRiskLevel
from app.modules.patient_agent.service import PatientAgentService
from app.modules.patients.models import Patient


class NoopRealtimeProvider(RealtimeAIProvider):
    name = "noop"

    async def create_session(self, request: RealtimeSessionRequest):  # noqa: ANN201
        raise AssertionError("provider session creation is not used by these tests")

    async def close_session(self, provider_session_ref: str) -> None:
        del provider_session_ref


def _principal(*, clinic_id, patient_id) -> PatientPrincipal:  # noqa: ANN001
    return PatientPrincipal(
        patient_id=patient_id,
        clinic_id=clinic_id,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


async def _active_session(
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
    )
    db_session.add(session)
    await db_session.commit()
    return session


@pytest.mark.asyncio
async def test_emergency_signal_is_server_classified_and_forces_handoff(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    session = await _active_session(db_session, test_clinic, test_patient)
    service = PatientAgentService(NoopRealtimeProvider())

    urgency = await service.assess_intake_risk(
        db=db_session,
        principal=_principal(clinic_id=test_clinic.id, patient_id=test_patient.id),
        session=session,
        reason="Patient reports difficulty breathing after facial swelling",
        signals=frozenset(
            {IntakeSignal.DIFFICULTY_BREATHING, IntakeSignal.FACIAL_OR_NECK_SWELLING}
        ),
    )
    await db_session.commit()

    assert urgency == AgentRiskLevel.EMERGENCY_ESCALATION
    assert session.context["intake_risk"] == "emergency_escalation"
    assert session.context["handoff_urgency"] == "emergency_escalation"
    assert session.handoff_state == "emergency_escalation"

    audits = (
        await db_session.execute(
            select(PatientAgentAuditEvent).where(PatientAgentAuditEvent.session_id == session.id)
        )
    ).scalars().all()
    assert {audit.event_type for audit in audits} >= {
        "intake_risk_assessed",
        "emergency_escalation_requested",
    }
    risk_audit = next(audit for audit in audits if audit.event_type == "intake_risk_assessed")
    assert risk_audit.detail["effective_urgency"] == "emergency_escalation"
    assert risk_audit.detail["diagnostic"] is False


@pytest.mark.asyncio
async def test_later_lower_risk_assessment_cannot_downgrade_emergency(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    session = await _active_session(db_session, test_clinic, test_patient)
    service = PatientAgentService(NoopRealtimeProvider())
    principal = _principal(clinic_id=test_clinic.id, patient_id=test_patient.id)

    first = await service.assess_intake_risk(
        db=db_session,
        principal=principal,
        session=session,
        reason="Patient reports uncontrolled bleeding",
        signals=frozenset({IntakeSignal.UNCONTROLLED_BLEEDING}),
    )
    second = await service.assess_intake_risk(
        db=db_session,
        principal=principal,
        session=session,
        reason="Patient also reports pain",
        signals=frozenset({IntakeSignal.PAIN}),
    )

    assert first == AgentRiskLevel.EMERGENCY_ESCALATION
    assert second == AgentRiskLevel.EMERGENCY_ESCALATION
    assert session.context["intake_risk"] == "emergency_escalation"
    assert session.handoff_state == "emergency_escalation"


@pytest.mark.asyncio
async def test_direct_handoff_uses_server_session_risk_not_client_urgency(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    session = await _active_session(db_session, test_clinic, test_patient)
    session.context = {"intake_risk": "urgent"}
    service = PatientAgentService(NoopRealtimeProvider())

    await service.request_handoff(
        db=db_session,
        principal=_principal(clinic_id=test_clinic.id, patient_id=test_patient.id),
        session=session,
        reason="Patient asks to speak with a clinician",
    )

    assert session.context["handoff_urgency"] == "urgent"
    audit = (
        await db_session.execute(
            select(PatientAgentAuditEvent).where(
                PatientAgentAuditEvent.session_id == session.id,
                PatientAgentAuditEvent.event_type == "human_handoff_requested",
            )
        )
    ).scalar_one()
    assert audit.detail["urgency"] == "urgent"
    assert audit.detail["server_derived_urgency"] is True


def test_realtime_tool_contract_does_not_let_model_assign_urgency() -> None:
    handoff_properties = PATIENT_HANDOFF_TOOL["parameters"]["properties"]
    assert "urgency" not in handoff_properties
    assert PATIENT_HANDOFF_TOOL["parameters"]["required"] == ["reason"]

    risk_properties = PATIENT_INTAKE_RISK_TOOL["parameters"]["properties"]
    assert "signals" in risk_properties
    assert "urgency" not in risk_properties
    assert "difficulty_breathing" in risk_properties["signals"]["items"]["enum"]
