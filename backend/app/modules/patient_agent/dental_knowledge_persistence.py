"""Database-backed retrieval for dentist-approved patient education knowledge."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

from .dental_conversation import DentalKnowledgeEntry, DentalKnowledgeRetriever, DentalTopic
from .models import PatientAgentDentalKnowledge
from .semantic_embeddings import (
    SEMANTIC_EMBEDDING_KEY,
    EmbeddingProvider,
    configured_embedding_provider,
    cosine_similarity,
    semantic_content_fingerprint,
)


def approved_dental_knowledge_query(
    *, clinic_id: uuid.UUID, locale: str, topic: DentalTopic | None
) -> Select[tuple[PatientAgentDentalKnowledge]]:
    stmt = select(PatientAgentDentalKnowledge).where(
        PatientAgentDentalKnowledge.clinic_id == clinic_id,
        PatientAgentDentalKnowledge.locale == locale,
        PatientAgentDentalKnowledge.review_status == "approved",
        PatientAgentDentalKnowledge.active.is_(True),
        PatientAgentDentalKnowledge.clinically_reviewed.is_(True),
        PatientAgentDentalKnowledge.approved_for_patient_education.is_(True),
        PatientAgentDentalKnowledge.reviewed_by.is_not(None),
        PatientAgentDentalKnowledge.retired_at.is_(None),
    )
    if topic is not None:
        stmt = stmt.where(PatientAgentDentalKnowledge.topic == topic.value)
    return stmt.order_by(
        PatientAgentDentalKnowledge.entry_key.asc(), PatientAgentDentalKnowledge.version.desc()
    )


class DatabaseDentalKnowledgeRetriever(DentalKnowledgeRetriever):
    """Clinic-scoped retriever that exposes only explicitly approved records."""

    def __init__(
        self,
        *,
        db: AsyncSession,
        clinic_id: uuid.UUID,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._db = db
        self._clinic_id = clinic_id
        self._embedding_provider = embedding_provider or configured_embedding_provider()

    async def search(
        self,
        *,
        query: str,
        locale: str,
        topic: DentalTopic | None,
        limit: int = 5,
    ) -> Sequence[DentalKnowledgeEntry]:
        if limit <= 0:
            return ()

        result = await self._db.execute(
            approved_dental_knowledge_query(
                clinic_id=self._clinic_id,
                locale=locale,
                topic=topic,
            )
        )
        rows = result.scalars().all()

        latest_by_key: dict[str, PatientAgentDentalKnowledge] = {}
        for row in rows:
            current = latest_by_key.get(row.entry_key)
            if current is None or row.version > current.version:
                latest_by_key[row.entry_key] = row

        terms = {term for term in query.casefold().strip().split() if len(term) >= 3}
        query_embedding = await self._safe_query_embedding(query)
        ranked: list[tuple[int, float, int, PatientAgentDentalKnowledge]] = []
        for row in latest_by_key.values():
            haystack = f"{row.title} {row.content}".casefold()
            lexical_score = sum(1 for term in terms if term in haystack)
            semantic_score = self._semantic_score(row, query_embedding)
            semantic_match = (
                semantic_score is not None
                and semantic_score >= settings.PATIENT_AGENT_SEMANTIC_MIN_SCORE
            )
            if terms and lexical_score == 0 and not semantic_match:
                continue
            ranked.append(
                (
                    1 if semantic_match else 0,
                    semantic_score if semantic_score is not None else -1.0,
                    lexical_score,
                    row,
                )
            )

        ranked.sort(
            key=lambda item: (
                -item[0],
                -item[1],
                -item[2],
                item[3].title.casefold(),
                item[3].entry_key,
            )
        )
        return tuple(self._to_entry(row) for *_, row in ranked[:limit])

    async def _safe_query_embedding(self, query: str) -> Sequence[float]:
        provider = self._embedding_provider
        if provider is None or not query.strip():
            return ()
        try:
            return tuple(await provider.embed(query))
        except Exception:
            return ()

    def _semantic_score(
        self,
        row: PatientAgentDentalKnowledge,
        query_embedding: Sequence[float],
    ) -> float | None:
        provider = self._embedding_provider
        if provider is None or not query_embedding:
            return None
        metadata = row.source_metadata or {}
        payload = metadata.get(SEMANTIC_EMBEDDING_KEY)
        if not isinstance(payload, dict) or payload.get("model") != provider.model:
            return None
        expected_fingerprint = semantic_content_fingerprint(title=row.title, content=row.content)
        if payload.get("content_sha256") != expected_fingerprint:
            return None
        vector = payload.get("vector")
        if not isinstance(vector, list) or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool) for value in vector
        ):
            return None
        dimensions = payload.get("dimensions")
        if not isinstance(dimensions, int) or dimensions != len(vector):
            return None
        return cosine_similarity(query_embedding, tuple(float(value) for value in vector))

    @staticmethod
    def _to_entry(row: PatientAgentDentalKnowledge) -> DentalKnowledgeEntry:
        return DentalKnowledgeEntry(
            entry_id=f"{row.entry_key}:v{row.version}",
            topic=DentalTopic(row.topic),
            title=row.title,
            content=row.content,
            source_name=row.source_name,
            source_reference=row.source_reference,
            reviewed_by=str(row.reviewed_by) if row.reviewed_by else None,
            locale=row.locale,
        )
