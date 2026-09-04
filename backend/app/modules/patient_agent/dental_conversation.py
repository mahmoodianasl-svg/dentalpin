"""Dental conversation intelligence primitives for the patient-facing agent.

This module intentionally separates professional dental education/intake dialogue
from diagnosis and treatment decisions. Retrieval implementations must return
curated, reviewable knowledge and the resulting dialogue must preserve the
patient-agent safety boundary.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .safety import AgentRiskLevel


class DentalTopic(StrEnum):
    PREVENTIVE_CARE = "preventive_care"
    RESTORATIVE = "restorative"
    ENDODONTICS = "endodontics"
    PERIODONTICS = "periodontics"
    PROSTHODONTICS = "prosthodontics"
    IMPLANTS = "implants"
    ORTHODONTICS = "orthodontics"
    ORAL_SURGERY = "oral_surgery"
    PEDIATRIC = "pediatric"
    COSMETIC = "cosmetic"
    DENTAL_EMERGENCY = "dental_emergency"
    APPOINTMENT_PREPARATION = "appointment_preparation"
    POST_TREATMENT_EDUCATION = "post_treatment_education"
    CLINIC_POLICY = "clinic_policy"


class IntakeSignal(StrEnum):
    PAIN = "pain"
    SWELLING = "swelling"
    BLEEDING = "bleeding"
    FEVER_OR_SYSTEMIC_ILLNESS = "fever_or_systemic_illness"
    TRAUMA = "trauma"
    DIFFICULTY_BREATHING = "difficulty_breathing"
    DIFFICULTY_SWALLOWING = "difficulty_swallowing"
    UNCONTROLLED_BLEEDING = "uncontrolled_bleeding"
    FACIAL_OR_NECK_SWELLING = "facial_or_neck_swelling"


@dataclass(frozen=True, slots=True)
class DentalKnowledgeEntry:
    entry_id: str
    topic: DentalTopic
    title: str
    content: str
    source_name: str
    source_reference: str
    reviewed_by: str | None = None
    locale: str = "en"


@dataclass(frozen=True, slots=True)
class DentalDialogueContext:
    patient_message: str
    locale: str
    topic: DentalTopic | None = None
    intake_signals: frozenset[IntakeSignal] = frozenset()


@dataclass(frozen=True, slots=True)
class DentalDialoguePlan:
    urgency: AgentRiskLevel
    answer_mode: str
    follow_up_questions: tuple[str, ...]
    must_handoff: bool
    knowledge: tuple[DentalKnowledgeEntry, ...]


class DentalKnowledgeRetriever(Protocol):
    async def search(
        self,
        *,
        query: str,
        locale: str,
        topic: DentalTopic | None,
        limit: int = 5,
    ) -> Sequence[DentalKnowledgeEntry]: ...


EMERGENCY_SIGNALS = frozenset(
    {
        IntakeSignal.DIFFICULTY_BREATHING,
        IntakeSignal.DIFFICULTY_SWALLOWING,
        IntakeSignal.UNCONTROLLED_BLEEDING,
    }
)

URGENT_SIGNALS = frozenset(
    {
        IntakeSignal.FACIAL_OR_NECK_SWELLING,
        IntakeSignal.TRAUMA,
        IntakeSignal.FEVER_OR_SYSTEMIC_ILLNESS,
    }
)


class DentalConversationPlanner:
    """Builds a safe dialogue plan from structured intake signals and curated RAG."""

    def __init__(self, retriever: DentalKnowledgeRetriever) -> None:
        self.retriever = retriever

    async def plan(self, context: DentalDialogueContext) -> DentalDialoguePlan:
        signals = context.intake_signals
        if signals & EMERGENCY_SIGNALS:
            urgency = AgentRiskLevel.EMERGENCY_ESCALATION
        elif signals & URGENT_SIGNALS:
            urgency = AgentRiskLevel.URGENT
        elif signals & {IntakeSignal.PAIN, IntakeSignal.SWELLING, IntakeSignal.BLEEDING}:
            urgency = AgentRiskLevel.SOON
        else:
            urgency = AgentRiskLevel.ROUTINE

        knowledge = tuple(
            await self.retriever.search(
                query=context.patient_message,
                locale=context.locale,
                topic=context.topic,
                limit=5,
            )
        )

        questions = self._follow_up_questions(signals)
        return DentalDialoguePlan(
            urgency=urgency,
            answer_mode="education_and_intake",
            follow_up_questions=questions,
            must_handoff=urgency in {AgentRiskLevel.URGENT, AgentRiskLevel.EMERGENCY_ESCALATION},
            knowledge=knowledge,
        )

    @staticmethod
    def _follow_up_questions(signals: frozenset[IntakeSignal]) -> tuple[str, ...]:
        questions: list[str] = []
        if IntakeSignal.PAIN in signals:
            questions.extend(("Where is the pain located?", "How long has the pain been present?"))
        if IntakeSignal.SWELLING in signals or IntakeSignal.FACIAL_OR_NECK_SWELLING in signals:
            questions.append("When did the swelling start, and is it getting worse?")
        if IntakeSignal.TRAUMA in signals:
            questions.append(
                "When did the injury happen, and is a tooth loose, displaced, or missing?"
            )
        return tuple(questions)


def build_dental_system_instructions(plan: DentalDialoguePlan) -> str:
    """Return provider-neutral instructions for a professional, bounded dental dialogue."""

    source_lines = "\n".join(
        f"- {entry.title} ({entry.source_name}; {entry.source_reference})"
        for entry in plan.knowledge
    )
    return (
        "You are a professional dental receptionist and patient education assistant. "
        "Use plain, calm, respectful language. Ask only relevant follow-up questions. "
        "Use the curated knowledge supplied below when explaining dental topics. "
        "Do not diagnose, prescribe medication, approve treatment, or alter/finalize clinical records. "
        "Do not present possibilities as confirmed conditions. Make uncertainty explicit. "
        "Appointment mutations require explicit patient confirmation. "
        "When the plan requires handoff, prioritize escalation to a human dental professional.\n"
        f"Urgency: {plan.urgency.value}\n"
        f"Human handoff required: {str(plan.must_handoff).lower()}\n"
        "Curated knowledge sources:\n"
        f"{source_lines or '- No curated source retrieved; keep the response limited to intake and handoff.'}"
    )
