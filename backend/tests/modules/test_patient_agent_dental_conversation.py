from __future__ import annotations

from app.modules.patient_agent.dental_conversation import (
    DentalConversationPlanner,
    DentalDialogueContext,
    DentalKnowledgeEntry,
    DentalTopic,
    IntakeSignal,
    build_dental_system_instructions,
)
from app.modules.patient_agent.safety import AgentRiskLevel


class StubRetriever:
    async def search(self, *, query: str, locale: str, topic: DentalTopic | None, limit: int = 5):
        assert query
        assert locale == "en"
        assert limit == 5
        return (
            DentalKnowledgeEntry(
                entry_id="kb-1",
                topic=topic or DentalTopic.PREVENTIVE_CARE,
                title="Reviewed patient education",
                content="General education only.",
                source_name="Clinic dental knowledge base",
                source_reference="kb://reviewed/1",
                reviewed_by="dentist-1",
            ),
        )


async def test_emergency_signal_forces_handoff() -> None:
    planner = DentalConversationPlanner(StubRetriever())
    plan = await planner.plan(
        DentalDialogueContext(
            patient_message="I am having trouble breathing after dental swelling",
            locale="en",
            topic=DentalTopic.DENTAL_EMERGENCY,
            intake_signals=frozenset({IntakeSignal.DIFFICULTY_BREATHING}),
        )
    )

    assert plan.urgency == AgentRiskLevel.EMERGENCY_ESCALATION
    assert plan.must_handoff is True
    assert plan.answer_mode == "education_and_intake"


async def test_urgent_signal_forces_handoff() -> None:
    planner = DentalConversationPlanner(StubRetriever())
    plan = await planner.plan(
        DentalDialogueContext(
            patient_message="My face is swollen",
            locale="en",
            intake_signals=frozenset({IntakeSignal.FACIAL_OR_NECK_SWELLING}),
        )
    )

    assert plan.urgency == AgentRiskLevel.URGENT
    assert plan.must_handoff is True
    assert "When did the swelling start, and is it getting worse?" in plan.follow_up_questions


async def test_pain_is_soon_and_collects_relevant_follow_up() -> None:
    planner = DentalConversationPlanner(StubRetriever())
    plan = await planner.plan(
        DentalDialogueContext(
            patient_message="My tooth hurts when I bite",
            locale="en",
            intake_signals=frozenset({IntakeSignal.PAIN}),
        )
    )

    assert plan.urgency == AgentRiskLevel.SOON
    assert plan.must_handoff is False
    assert plan.follow_up_questions == (
        "Where is the pain located?",
        "How long has the pain been present?",
    )


async def test_routine_education_uses_curated_knowledge_without_clinical_authority() -> None:
    planner = DentalConversationPlanner(StubRetriever())
    plan = await planner.plan(
        DentalDialogueContext(
            patient_message="What is a dental implant?",
            locale="en",
            topic=DentalTopic.IMPLANTS,
        )
    )

    instructions = build_dental_system_instructions(plan)

    assert plan.urgency == AgentRiskLevel.ROUTINE
    assert plan.must_handoff is False
    assert "Reviewed patient education" in instructions
    assert "Do not diagnose" in instructions
    assert "prescribe medication" in instructions
    assert "Appointment mutations require explicit patient confirmation" in instructions


async def test_no_curated_result_limits_dialogue_to_intake_and_handoff() -> None:
    class EmptyRetriever:
        async def search(self, *, query: str, locale: str, topic: DentalTopic | None, limit: int = 5):
            return ()

    planner = DentalConversationPlanner(EmptyRetriever())
    plan = await planner.plan(
        DentalDialogueContext(
            patient_message="Tell me what disease I have",
            locale="en",
        )
    )

    instructions = build_dental_system_instructions(plan)
    assert "No curated source retrieved; keep the response limited to intake and handoff." in instructions
    assert "Do not present possibilities as confirmed conditions." in instructions
