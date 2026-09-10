from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.patient_agent.dental_knowledge_review_service import DentalKnowledgeReviewService
from app.modules.patient_agent.models import PatientAgentAuditEvent
from app.modules.patient_agent.semantic_embeddings import SEMANTIC_EMBEDDING_KEY


class FakeEmbeddingProvider:
    def __init__(self, *, vector: tuple[float, ...] = (1.0, 0.0)) -> None:
        self._vector = vector

    @property
    def model(self) -> str:
        return "test-embedding"

    async def embed(self, text: str) -> tuple[float, ...]:
        assert "Implant" in text
        return self._vector


class FailingEmbeddingProvider(FakeEmbeddingProvider):
    async def embed(self, text: str) -> tuple[float, ...]:
        del text
        raise RuntimeError("provider unavailable")


def _record(*, status: str = "in_review") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        clinic_id=uuid.uuid4(),
        entry_key="implant-basics",
        version=1,
        review_status=status,
        submitted_by=uuid.uuid4(),
        submitted_at=None,
        reviewed_by=None,
        reviewed_at=None,
        decision_note=None,
        clinically_reviewed=False,
        approved_for_patient_education=False,
        active=True,
        retired_at=None,
        title="Implant basics",
        content="Reviewed patient education about dental implants.",
        source_metadata={"source_kind": "curated"},
    )


def _db_for(record: SimpleNamespace) -> tuple[SimpleNamespace, list[object]]:
    added: list[object] = []
    result = SimpleNamespace(scalar_one_or_none=lambda: record)
    db = SimpleNamespace(
        execute=AsyncMock(return_value=result),
        add=lambda value: added.append(value),
        flush=AsyncMock(),
    )
    return db, added


@pytest.mark.asyncio
async def test_approval_indexes_content_when_provider_available() -> None:
    record = _record()
    db, added = _db_for(record)

    result = await DentalKnowledgeReviewService(
        embedding_provider=FakeEmbeddingProvider()
    ).approve(
        db=db,
        clinic_id=record.clinic_id,
        record_id=record.id,
        actor_user_id=uuid.uuid4(),
    )

    payload = result.source_metadata[SEMANTIC_EMBEDDING_KEY]
    assert payload["model"] == "test-embedding"
    assert payload["dimensions"] == 2
    assert payload["vector"] == [1.0, 0.0]
    assert len(payload["content_sha256"]) == 64
    audits = [item for item in added if isinstance(item, PatientAgentAuditEvent)]
    assert audits[-1].detail["semantic_indexed"] is True


@pytest.mark.asyncio
async def test_approval_remains_successful_when_embedding_provider_fails() -> None:
    record = _record()
    record.source_metadata[SEMANTIC_EMBEDDING_KEY] = {"stale": True}
    db, added = _db_for(record)

    result = await DentalKnowledgeReviewService(
        embedding_provider=FailingEmbeddingProvider()
    ).approve(
        db=db,
        clinic_id=record.clinic_id,
        record_id=record.id,
        actor_user_id=uuid.uuid4(),
    )

    assert result.review_status == "approved"
    assert SEMANTIC_EMBEDDING_KEY not in result.source_metadata
    audits = [item for item in added if isinstance(item, PatientAgentAuditEvent)]
    assert audits[-1].detail["semantic_indexed"] is False


@pytest.mark.asyncio
async def test_submit_and_reject_remove_stale_semantic_embedding() -> None:
    stale = {"model": "old", "vector": [1.0]}
    record = _record(status="rejected")
    record.source_metadata[SEMANTIC_EMBEDDING_KEY] = stale
    db, _ = _db_for(record)

    submitted = await DentalKnowledgeReviewService().submit(
        db=db,
        clinic_id=record.clinic_id,
        record_id=record.id,
        actor_user_id=uuid.uuid4(),
    )
    assert SEMANTIC_EMBEDDING_KEY not in submitted.source_metadata

    submitted.source_metadata[SEMANTIC_EMBEDDING_KEY] = stale
    rejected = await DentalKnowledgeReviewService().reject(
        db=db,
        clinic_id=record.clinic_id,
        record_id=record.id,
        actor_user_id=uuid.uuid4(),
        decision_note="Needs revision",
    )
    assert SEMANTIC_EMBEDDING_KEY not in rejected.source_metadata


@pytest.mark.asyncio
async def test_reindex_requires_current_patient_education_eligibility() -> None:
    record = _record(status="approved")
    record.reviewed_by = uuid.uuid4()
    record.clinically_reviewed = True
    record.approved_for_patient_education = True
    record.active = False
    db, _ = _db_for(record)

    with pytest.raises(ValueError, match="Only active approved"):
        await DentalKnowledgeReviewService(
            embedding_provider=FakeEmbeddingProvider()
        ).reindex(
            db=db,
            clinic_id=record.clinic_id,
            record_id=record.id,
            actor_user_id=uuid.uuid4(),
        )


@pytest.mark.asyncio
async def test_reindex_refreshes_embedding_and_writes_audit() -> None:
    record = _record(status="approved")
    record.reviewed_by = uuid.uuid4()
    record.clinically_reviewed = True
    record.approved_for_patient_education = True
    db, added = _db_for(record)

    result = await DentalKnowledgeReviewService(
        embedding_provider=FakeEmbeddingProvider(vector=(0.5, 0.5))
    ).reindex(
        db=db,
        clinic_id=record.clinic_id,
        record_id=record.id,
        actor_user_id=uuid.uuid4(),
    )

    assert result.source_metadata[SEMANTIC_EMBEDDING_KEY]["vector"] == [0.5, 0.5]
    audits = [item for item in added if isinstance(item, PatientAgentAuditEvent)]
    assert audits[-1].event_type == "dental_knowledge_semantic_reindexed"
    assert audits[-1].detail["semantic_indexed"] is True
