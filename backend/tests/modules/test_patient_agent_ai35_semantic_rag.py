from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.patient_agent.dental_conversation import DentalTopic
from app.modules.patient_agent.dental_knowledge_persistence import DatabaseDentalKnowledgeRetriever
from app.modules.patient_agent.models import PatientAgentDentalKnowledge
from app.modules.patient_agent.semantic_embeddings import cosine_similarity


class FakeEmbeddingProvider:
    def __init__(self, *, vector: tuple[float, ...], model: str = "test-embedding") -> None:
        self._vector = vector
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def embed(self, text: str) -> tuple[float, ...]:
        assert text
        return self._vector


class FailingEmbeddingProvider(FakeEmbeddingProvider):
    async def embed(self, text: str) -> tuple[float, ...]:
        del text
        raise RuntimeError("embedding provider unavailable")


class FakeScalars:
    def __init__(self, rows: list[PatientAgentDentalKnowledge]) -> None:
        self._rows = rows

    def all(self) -> list[PatientAgentDentalKnowledge]:
        return self._rows


class FakeResult:
    def __init__(self, rows: list[PatientAgentDentalKnowledge]) -> None:
        self._rows = rows

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._rows)


class FakeDb(SimpleNamespace):
    def __init__(self, rows: list[PatientAgentDentalKnowledge]) -> None:
        super().__init__()
        self._rows = rows

    async def execute(self, statement):  # noqa: ANN001, ANN201
        assert statement is not None
        return FakeResult(self._rows)


def _approved_row(
    *,
    entry_key: str,
    title: str,
    content: str,
    vector: list[float] | None,
    model: str = "test-embedding",
) -> PatientAgentDentalKnowledge:
    metadata: dict[str, object] = {}
    if vector is not None:
        metadata["semantic_embedding"] = {
            "model": model,
            "dimensions": len(vector),
            "vector": vector,
        }
    return PatientAgentDentalKnowledge(
        id=uuid4(),
        clinic_id=uuid4(),
        entry_key=entry_key,
        version=1,
        topic=DentalTopic.IMPLANTS.value,
        locale="en",
        title=title,
        content=content,
        source_name="Clinic knowledge",
        source_reference=f"kb://{entry_key}/1",
        source_metadata=metadata,
        review_status="approved",
        active=True,
        clinically_reviewed=True,
        approved_for_patient_education=True,
        reviewed_by=uuid4(),
    )


def test_cosine_similarity_rejects_invalid_vectors() -> None:
    assert cosine_similarity((), (1.0,)) is None
    assert cosine_similarity((1.0,), (1.0, 0.0)) is None
    assert cosine_similarity((0.0, 0.0), (1.0, 0.0)) is None


def test_cosine_similarity_scores_aligned_vectors() -> None:
    assert cosine_similarity((1.0, 0.0), (1.0, 0.0)) == pytest.approx(1.0)
    assert cosine_similarity((1.0, 0.0), (0.0, 1.0)) == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_semantic_ranking_can_retrieve_lexical_miss() -> None:
    semantic_match = _approved_row(
        entry_key="implant-aftercare",
        title="After surgery care",
        content="Keep the area clean and follow the clinician's reviewed instructions.",
        vector=[1.0, 0.0],
    )
    unrelated = _approved_row(
        entry_key="implant-materials",
        title="Implant materials",
        content="Patient education about common implant materials.",
        vector=[0.0, 1.0],
    )
    clinic_id = semantic_match.clinic_id
    unrelated.clinic_id = clinic_id
    retriever = DatabaseDentalKnowledgeRetriever(
        db=FakeDb([semantic_match, unrelated]),
        clinic_id=clinic_id,
        embedding_provider=FakeEmbeddingProvider(vector=(1.0, 0.0)),
    )

    results = await retriever.search(
        query="healing guidance",
        locale="en",
        topic=DentalTopic.IMPLANTS,
        limit=5,
    )

    assert [entry.entry_id for entry in results] == ["implant-aftercare:v1"]


@pytest.mark.asyncio
async def test_embedding_failure_falls_back_to_lexical_ranking() -> None:
    lexical_match = _approved_row(
        entry_key="implant-basics",
        title="Dental implant basics",
        content="Reviewed patient education about implant appointments.",
        vector=[1.0, 0.0],
    )
    clinic_id = lexical_match.clinic_id
    retriever = DatabaseDentalKnowledgeRetriever(
        db=FakeDb([lexical_match]),
        clinic_id=clinic_id,
        embedding_provider=FailingEmbeddingProvider(vector=(1.0, 0.0)),
    )

    results = await retriever.search(
        query="implant appointment",
        locale="en",
        topic=DentalTopic.IMPLANTS,
        limit=5,
    )

    assert [entry.entry_id for entry in results] == ["implant-basics:v1"]


@pytest.mark.asyncio
async def test_wrong_embedding_model_does_not_create_semantic_match() -> None:
    row = _approved_row(
        entry_key="implant-aftercare",
        title="After surgery care",
        content="Reviewed aftercare guidance.",
        vector=[1.0, 0.0],
        model="different-model",
    )
    retriever = DatabaseDentalKnowledgeRetriever(
        db=FakeDb([row]),
        clinic_id=row.clinic_id,
        embedding_provider=FakeEmbeddingProvider(vector=(1.0, 0.0)),
    )

    results = await retriever.search(
        query="healing guidance",
        locale="en",
        topic=DentalTopic.IMPLANTS,
        limit=5,
    )

    assert results == ()
