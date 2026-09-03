from app.modules.patient_agent.safety import (
    action_allowed_without_confirmation,
    requires_human_approval,
    requires_patient_confirmation,
)
from app.modules.patient_agent.schemas import FoundationStatus


def test_clinical_actions_are_never_autonomous() -> None:
    for action in (
        "diagnose",
        "prescribe",
        "alter_clinical_record",
        "finalize_clinical_note",
        "approve_treatment_plan",
    ):
        assert not action_allowed_without_confirmation(action)
        assert requires_human_approval(action)


def test_appointment_mutations_require_explicit_confirmation() -> None:
    for action in ("create_appointment", "reschedule_appointment", "cancel_appointment"):
        assert not action_allowed_without_confirmation(action)
        assert requires_patient_confirmation(action)
        assert not requires_human_approval(action)


def test_read_only_actions_remain_available() -> None:
    for action in (
        "get_my_profile",
        "get_upcoming_appointments",
        "search_available_slots",
        "search_patient_education",
    ):
        assert action_allowed_without_confirmation(action)


def test_foundation_is_disabled_by_default() -> None:
    status = FoundationStatus()
    assert status.phase == "AI-0"
    assert status.enabled is False
    assert status.capabilities.text is True
    assert status.capabilities.voice is True
    assert status.capabilities.video is True
    assert status.capabilities.autonomous_diagnosis is False
    assert status.capabilities.autonomous_prescribing is False
    assert status.capabilities.autonomous_clinical_writes is False
    assert {item.consent_type for item in status.consent if item.required} == {
        "ai",
        "audio",
        "video",
    }
