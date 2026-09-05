from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.modules.patient_agent.dental_conversation import DentalTopic
from app.modules.patient_agent.dental_knowledge_persistence import (
    DatabaseDentalKnowledgeRetriever,
    approved_dental_knowledge_query,
)


def _row(
    entry_key: str,
    *,
    version: int = 1,
    title: str = "Dental implant guide",
    content: str = "General information about dental implant treatment and appointments.",
    topic: str = "implants",
    locale: str = "en",
):
    return SimpleNamespace(
        entry_key=entry_key,
        version=version,
        title=title,
        content=content,
        topic=topic,
        locale=locale,
        source_name="Clinic reviewed knowledge",
        source_reference=f"kb://{entry_key}/{version}",
        reviewed_by=uuid.uuid4(),
        reviewed_at=datetime.now(UTC),
    )


def _db_with_rows(rows):
    scalar_result = SimpleNamespace(all=lambda: list(rows))
    execute_result = SimpleNamespace(scalars=lambda: scalar_result)
    db = SimpleNamespace(execute=AsyncMock(return_value=execute_result))
    return db


def test_approved_query_is_clinic_scoped_and_enforces_safety_filters() -> None:
    stmt = approved_dental_knowledge_query(
        clinic_id=uuid.uuid4(), locale="en", topic=DentalTopic.IMPLANTS
    )
    sql = str(stmt)

    assert "patient_agent_dental_knowledge.clinic_id" in sql
    assert "patient_agent_dental_knowledge.locale" in sql
    assert "patient_agent_dental_knowledge.review_status" in sql
    assert "patient_agent_dental_knowledge.active IS true" in sql
    assert "patient_agent_dental_knowledge.clinically_reviewed IS true" in sql
    assert "patient_agent_dental_knowledge.approved_for_patient_education IS true" in sql
    assert "patient_agent_dental_knowledge.reviewed_by IS NOT NULL" in sql
    assert "patient_agent_dental_knowledge.retired_at IS NULL" in sql
    assert "patient_agent_dental_knowledge.topic" in sql


async def test_database_retriever_returns_only_latest_version_per_entry_key() -> None:
    db = _db_with_rows(
        (
            _row("implant-basics", version=1, title="Old implant guide"),
            _row("implant-basics", version=2, title="Current implant guide"),
            _row("implant-aftercare", version=1, title="Implant aftercare"),
        )
    )
    retriever = DatabaseDentalKnowledgeRetriever(db=db, clinic_id=uuid.uuid4())

    results = await retriever.search(
        query="implant", locale="en", topic=DentalTopic.IMPLANTS, limit=5
    )

    assert {entry.entry_id for entry in results} == {
        "implant-basics:v2",
        "implant-aftercare:v1",
    }
    assert all(entry.reviewed_by for entry in results)


async def test_database_retriever_preserves_lexical_suppression_and_limit() -> None:
    db = _db_with_rows(
        (
            _row(
                "implant-appointment",
                title="Dental implant appointment",
                content="implant appointment planning",
            ),
            _row("implant-general", title="Dental implant guide", content="implant information"),
        )
    )
    retriever = DatabaseDentalKnowledgeRetriever(db=db, clinic_id=uuid.uuid4())

    results = await retriever.search(
        query="implant appointment",
        locale="en",
        topic=DentalTopic.IMPLANTS,
        limit=1,
    )
    assert [entry.entry_id for entry in results] == ["implant-appointment:v1"]

    assert await retriever.search(
        query="root canal", locale="en", topic=DentalTopic.IMPLANTS
    ) == ()


async def test_database_retriever_does_not_query_for_nonpositive_limit() -> None:
    db = _db_with_rows((_row("implant"),))
    retriever = DatabaseDentalKnowledgeRetriever(db=db, clinic_id=uuid.uuid4())

    assert await retriever.search(
        query="implant", locale="en", topic=DentalTopic.IMPLANTS, limit=0
    ) == ()
    db.execute.assert_not_awaited()
