"""Safety policy for the patient-facing agent.

The realtime agent may converse, retrieve authorized context, collect intake,
explain approved information, and propose administrative actions. It may not
autonomously diagnose, prescribe, alter clinical records, or execute sensitive
writes without an explicit confirmation/human approval boundary.
"""
from __future__ import annotations

from enum import StrEnum


class AgentRiskLevel(StrEnum):
    ROUTINE = "routine"
    SOON = "soon"
    URGENT = "urgent"
    EMERGENCY_ESCALATION = "emergency_escalation"


AUTONOMOUSLY_FORBIDDEN = frozenset({
    "diagnose",
    "prescribe",
    "alter_clinical_record",
    "finalize_clinical_note",
    "approve_treatment_plan",
})

CONFIRMATION_REQUIRED = frozenset({
    "create_appointment",
    "reschedule_appointment",
    "cancel_appointment",
    "send_patient_message",
    "record_payment_intent",
})


def action_allowed_without_confirmation(action: str) -> bool:
    return action not in AUTONOMOUSLY_FORBIDDEN and action not in CONFIRMATION_REQUIRED


def requires_human_approval(action: str) -> bool:
    return action in AUTONOMOUSLY_FORBIDDEN


def requires_patient_confirmation(action: str) -> bool:
    return action in CONFIRMATION_REQUIRED
