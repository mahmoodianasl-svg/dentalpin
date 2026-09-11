from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.patient_agent.dental_conversation import DentalTopic
from app.modules.patient_agent.dental_knowledge_ingestion_schemas import (
    DentalKnowledgeCorpusEntry,
    DentalKnowledgeCorpusImportRequest,
)
from app.modules.patient_agent.dental_knowledge_ingestion_service import (
    DentalKnowledgeCorpusIngestionService,
)
from app.modules.patient_agent.models import PatientAgentAuditEvent, PatientAgentDentalKnowledge
from app.modules.patient_agent.semantic_embeddings import SEMANTIC_EMBEDDING_KEY


def _payload(\n    *, content: str = "Brush twice daily with fluoride toothpaste."\n) -> DentalKnowledgeCorpusImportRequest:
    return DentalKnowledgeCorpusImportRequest(
        corpus_id="ada-preventive",
        corpus_version="2026-09",
        entries=[
            DentalKnowledgeCorpusEntry(
                entry_key="preventive.brushing",
                topic=DentalTopic.PREVENTIVE_CARE,
                locale="en",
                title="Brushing basics",
                content=content,
                source_name="Curated dental guidance",
                source_reference="https://example.invalid/preventive/brushing",
                source_metadata={
                    "publisher": "example",
                    SEMANTIC_EMBEDDING_KEY: {"model": "untrusted", "vector": [1.0]},
                    "ingestion": {"content_sha256": "spoofed"},
                },
            )
        ],
    )


def _db_with_latest(latest: object | None) -> tuple[SimpleNamespace, list[object]]:
    added: list[object] = []
    result = SimpleNamespace(scalar_one_or_none=lambda: latest)
    db = SimpleNamespace(
        execute=AsyncMock(return_value=result),
        add=lambda value: added.append(value),
        flush=AsyncMock(),
    )
    return db, added


@pytest.mark.asyncio
async def test_ingest_creates_inactive_draft_and_sanitizes_reserved_metadata() -> None:
    db, added = _db_with_latest(None)
    clinic_id = uuid.uuid4()
    actor_user_id = uuid.uuid4()

    result = await DentalKnowledgeCorpusIngestionService().ingest(
        db=db,
        clinic_id=clinic_id,
        actor_user_id=actor_user_id,
        payload=_payload(),
    )

    assert len(result.created) == 1
    assert not result.skipped
    record = result.created[0]
    assert record.clinic_id == clinic_id
    assert record.version == 1
    assert record.review_status == "draft"
    assert record.active is False
    assert record.clinically_reviewed is False
    assert record.approved_for_patient_education is False
    assert record.reviewed_by is None
    assert SEMANTIC_EMBEDDING_KEY not in record.source_metadata
    assert record.source_metadata["publisher"] == "example"
    assert record.source_metadata["ingestion"]["corpus_id"] == "ada-preventive"
    assert record.source_metadata["ingestion"]["content_sha256"] != "spoofed"

    audits = [item for item in added if isinstance(item, PatientAgentAuditEvent)]
    assert audits[-1].event_type == "dental_knowledge_corpus_entry_ingested"
    assert audits[-1].detail["review_status"] == "draft"


@pytest.mark.asyncio
async def test_unchanged_latest_entry_is_skipped_idempotently() -> None:
    service = DentalKnowledgeCorpusIngestionService()
    entry = _payload().entries[0]
    fingerprint = service._fingerprint(entry)
    latest = SimpleNamespace(
        id=uuid.uuid4(),
        clinic_id=uuid.uuid4(),
        entry_key=entry.entry_key,
        version=3,
        review_status="approved",
        source_metadata={"ingestion": {"content_sha256": fingerprint}},
    )
    db, added = _db_with_latest(latest)

    result = await service.ingest(
        db=db,
        clinic_id=latest.clinic_id,
        actor_user_id=uuid.uuid4(),
        payload=_payload(),
    )

    assert not result.created
    assert result.skipped == (latest,)
    audits = [item for item in added if isinstance(item, PatientAgentAuditEvent)]
    assert audits[-1].event_type == "dental_knowledge_corpus_entry_skipped"
    assert audits[-1].outcome == "unchanged"


@pytest.mark.asyncio
async def test_changed_entry_creates_next_draft_version_without_altering_prior_record() -> None:
    latest = SimpleNamespace(
        id=uuid.uuid4(),
        clinic_id=uuid.uuid4(),
        entry_key="preventive.brushing",
        version=4,
        review_status="approved",
        source_metadata={"ingestion": {"content_sha256": "0" * 64}},
    )
    db, added = _db_with_latest(latest)

    result = await DentalKnowledgeCorpusIngestionService().ingest(
        db=db,
        clinic_id=latest.clinic_id,
        actor_user_id=uuid.uuid4(),
        payload=_payload(content="Updated clinically curated brushing guidance."),
    )

    assert len(result.created) == 1
    record = result.created[0]
    assert isinstance(record, PatientAgentDentalKnowledge)
    assert record.version == 5
    assert record.review_status == "draft"
    assert record.active is False
    assert latest.version == 4
    assert latest.review_status == "approved"
    assert record in added


@pytest.mark.asyncio
async def test_duplicate_entry_keys_in_one_payload_are_rejected_before_writes() -> None:
    payload = _payload()
    payload.entries.append(payload.entries[0].model_copy())
    db, added = _db_with_latest(None)

    with pytest.raises(ValueError, match="Duplicate corpus entry_key"):
        await DentalKnowledgeCorpusIngestionService().ingest(
            db=db,
            clinic_id=uuid.uuid4(),
            actor_user_id=uuid.uuid4(),
            payload=payload,
        )

    db.execute.assert_not_awaited()
    assert not added
