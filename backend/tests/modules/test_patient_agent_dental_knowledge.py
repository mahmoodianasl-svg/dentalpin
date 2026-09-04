from __future__ import annotations

from app.modules.patient_agent.dental_conversation import DentalKnowledgeEntry, DentalTopic
from app.modules.patient_agent.dental_knowledge import (
    CuratedDentalKnowledgeRecord,
    CuratedDentalKnowledgeRetriever,
)


def _entry(
    entry_id: str,
    *,
    title: str = "Dental implant patient guide",
    content: str = "General information about dental implants and appointments.",
    topic: DentalTopic = DentalTopic.IMPLANTS,
    locale: str = "en",
    reviewed_by: str | None = "dentist-1",
) -> DentalKnowledgeEntry:
    return DentalKnowledgeEntry(
        entry_id=entry_id,
        topic=topic,
        title=title,
        content=content,
        source_name="Clinic reviewed knowledge",
        source_reference=f"kb://{entry_id}",
        reviewed_by=reviewed_by,
        locale=locale,
    )


async def test_only_fully_reviewed_patient_education_content_is_retrieved() -> None:
    retriever = CuratedDentalKnowledgeRetriever(
        (
            CuratedDentalKnowledgeRecord(
                _entry("approved"),
                clinically_reviewed=True,
                approved_for_patient_education=True,
            ),
            CuratedDentalKnowledgeRecord(
                _entry("unreviewed"),
                clinically_reviewed=False,
                approved_for_patient_education=True,
            ),
            CuratedDentalKnowledgeRecord(
                _entry("not-patient-approved"),
                clinically_reviewed=True,
                approved_for_patient_education=False,
            ),
            CuratedDentalKnowledgeRecord(
                _entry("missing-reviewer", reviewed_by=None),
                clinically_reviewed=True,
                approved_for_patient_education=True,
            ),
        )
    )

    results = await retriever.search(query="dental implant", locale="en", topic=DentalTopic.IMPLANTS)

    assert [entry.entry_id for entry in results] == ["approved"]


async def test_inactive_content_is_never_retrieved() -> None:
    retriever = CuratedDentalKnowledgeRetriever(
        (
            CuratedDentalKnowledgeRecord(
                _entry("inactive"),
                active=False,
                clinically_reviewed=True,
                approved_for_patient_education=True,
            ),
        )
    )

    assert await retriever.search(query="implant", locale="en", topic=DentalTopic.IMPLANTS) == ()


async def test_locale_and_topic_boundaries_are_enforced() -> None:
    retriever = CuratedDentalKnowledgeRetriever(
        (
            CuratedDentalKnowledgeRecord(
                _entry("english-implant"),
                clinically_reviewed=True,
                approved_for_patient_education=True,
            ),
            CuratedDentalKnowledgeRecord(
                _entry("turkish-implant", locale="tr"),
                clinically_reviewed=True,
                approved_for_patient_education=True,
            ),
            CuratedDentalKnowledgeRecord(
                _entry("english-ortho", topic=DentalTopic.ORTHODONTICS),
                clinically_reviewed=True,
                approved_for_patient_education=True,
            ),
        )
    )

    results = await retriever.search(query="implant", locale="en", topic=DentalTopic.IMPLANTS)

    assert [entry.entry_id for entry in results] == ["english-implant"]


async def test_lexical_ranking_is_deterministic_and_limit_is_respected() -> None:
    retriever = CuratedDentalKnowledgeRetriever(
        (
            CuratedDentalKnowledgeRecord(
                _entry("strong", title="Dental implant appointment", content="implant appointment implant"),
                clinically_reviewed=True,
                approved_for_patient_education=True,
            ),
            CuratedDentalKnowledgeRecord(
                _entry("weak", title="Dental implant guide", content="implant information"),
                clinically_reviewed=True,
                approved_for_patient_education=True,
            ),
        )
    )

    results = await retriever.search(
        query="implant appointment",
        locale="en",
        topic=DentalTopic.IMPLANTS,
        limit=1,
    )

    assert [entry.entry_id for entry in results] == ["strong"]


async def test_unmatched_query_does_not_inject_unrelated_content() -> None:
    retriever = CuratedDentalKnowledgeRetriever(
        (
            CuratedDentalKnowledgeRecord(
                _entry("implant"),
                clinically_reviewed=True,
                approved_for_patient_education=True,
            ),
        )
    )

    assert await retriever.search(query="root canal", locale="en", topic=DentalTopic.IMPLANTS) == ()
