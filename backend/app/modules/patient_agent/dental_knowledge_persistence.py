"""Database-backed retrieval for dentist-approved patient education knowledge."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from .dental_conversation import DentalKnowledgeEntry, DentalKnowledgeRetriever, DentalTopic
from .models import PatientAgentDentalKnowledge


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

    def __init__(self, *, db: AsyncSession, clinic_id: uuid.UUID) -> None:
        self._db = db
        self._clinic_id = clinic_id

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
        ranked: list[tuple[int, PatientAgentDentalKnowledge]] = []
        for row in latest_by_key.values():
            haystack = f"{row.title} {row.content}".casefold()
            score = sum(1 for term in terms if term in haystack)
            if terms and score == 0:
                continue
            ranked.append((score, row))

        ranked.sort(key=lambda item: (-item[0], item[1].title.casefold(), item[1].entry_key))
        return tuple(self._to_entry(row) for _, row in ranked[:limit])

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
