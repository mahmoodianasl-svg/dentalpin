from app.modules.patient_agent import PatientAgentModule
from app.modules.patient_agent.models import PatientAgentDentalKnowledge


def test_dentist_has_knowledge_review_permissions_but_receptionist_does_not() -> None:
    manifest = PatientAgentModule.manifest

    assert "knowledge.read" in manifest["role_permissions"]["dentist"]
    assert "knowledge.review" in manifest["role_permissions"]["dentist"]
    assert "knowledge.read" not in manifest["role_permissions"]["receptionist"]
    assert "knowledge.review" not in manifest["role_permissions"]["receptionist"]


def test_persistent_knowledge_model_is_registered_with_module() -> None:
    assert PatientAgentDentalKnowledge in PatientAgentModule().get_models()
