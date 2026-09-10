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
from app.modules.patient_agent.router import patient_dental_knowledge_search
from app.modules.patient_agent.safety import AgentRiskLevel
from app.modules.patient_agent.schemas import PatientDentalKnowledgeSearchRequest
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
    await db_session.flush()
    return session


@pytest.mark.asyncio
async def test_intake_and_auto_handoff_audits_are_metadata_only(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    session = await _active_session(db_session, test_clinic, test_patient)
    principal = _principal(clinic_id=test_clinic.id, patient_id=test_patient.id)
    service = PatientAgentService(NoopRealtimeProvider())
    patient_summary = "Patient says they cannot breathe and their face is swelling badly"

    urgency = await service.assess_intake_risk(
        db=db_session,
        principal=principal,
        session=session,
        reason=patient_summary,
        signals=frozenset(
            {IntakeSignal.DIFFICULTY_BREATHING, IntakeSignal.FACIAL_OR_NECK_SWELLING}
        ),
    )
    await db_session.flush()

    assert urgency == AgentRiskLevel.EMERGENCY_ESCALATION
    events = (
        await db_session.execute(
            select(PatientAgentAuditEvent).where(PatientAgentAuditEvent.session_id == session.id)
        )
    ).scalars().all()
    risk_audit = next(event for event in events if event.event_type == "intake_risk_assessed")
    escalation_audit = next(
        event for event in events if event.event_type == "emergency_escalation_requested"
    )

    assert risk_audit.actor_type == "system"
    assert risk_audit.reason == "Deterministic intake risk classification"
    assert risk_audit.detail["tool_name"] == "assess_patient_intake_risk"
    assert risk_audit.detail["requires_handoff"] is True
    assert risk_audit.detail["safety_decision"] == "emergency_escalation"
    assert patient_summary not in str(risk_audit.detail)

    assert escalation_audit.actor_type == "system"
    assert escalation_audit.reason == "Emergency escalation requested"
    assert escalation_audit.detail["tool_name"] == "request_patient_human_handoff"
    assert escalation_audit.detail["urgency_source"] == "server_session"
    assert escalation_audit.detail["server_derived_urgency"] is True
    assert patient_summary not in str(escalation_audit.detail)


@pytest.mark.asyncio
async def test_direct_handoff_audit_marks_trusted_api_urgency_raise(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    session = await _active_session(db_session, test_clinic, test_patient)
    principal = _principal(clinic_id=test_clinic.id, patient_id=test_patient.id)
    service = PatientAgentService(NoopRealtimeProvider())
    patient_summary = "Patient asks to speak to a clinician about a worsening issue"

    await service.request_handoff(
        db=db_session,
        principal=principal,
        session=session,
        reason=patient_summary,
        urgency=AgentRiskLevel.URGENT,
    )
    await db_session.flush()

    audit = (
        await db_session.execute(
            select(PatientAgentAuditEvent).where(
                PatientAgentAuditEvent.session_id == session.id,
                PatientAgentAuditEvent.event_type == "human_handoff_requested",
            )
        )
    ).scalar_one()
    assert audit.actor_type == "patient"
    assert audit.reason == "Human handoff requested"
    assert audit.detail["urgency"] == "urgent"
    assert audit.detail["urgency_source"] == "trusted_api_raise"
    assert audit.detail["server_derived_urgency"] is False
    assert audit.detail["safety_decision"] == "requested"
    assert patient_summary not in str(audit.detail)


@pytest.mark.asyncio
async def test_knowledge_search_fallback_audit_omits_raw_query(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    principal = _principal(clinic_id=test_clinic.id, patient_id=test_patient.id)
    raw_query = "unmatchableauditneedle"

    response = await patient_dental_knowledge_search(
        payload=PatientDentalKnowledgeSearchRequest(query=raw_query, locale="en", limit=5),
        principal=principal,
        db=db_session,
    )

    assert response.data.fallback_required is True
    audit = (
        await db_session.execute(
            select(PatientAgentAuditEvent).where(
                PatientAgentAuditEvent.clinic_id == test_clinic.id,
                PatientAgentAuditEvent.patient_id == test_patient.id,
                PatientAgentAuditEvent.event_type == "patient_knowledge_search_completed",
            )
        )
    ).scalar_one()
    assert audit.session_id is None
    assert audit.actor_type == "system"
    assert audit.outcome == "fallback"
    assert audit.reason == "Clinic-approved patient education knowledge lookup"
    assert audit.detail["tool_name"] == "search_patient_dental_knowledge"
    assert audit.detail["result_count"] == 0
    assert audit.detail["fallback_required"] is True
    assert audit.detail["query_length"] == len(raw_query)
    assert audit.detail["patient_education_only"] is True
    assert raw_query not in str(audit.detail)
