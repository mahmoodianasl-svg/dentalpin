"""Curated dental knowledge retrieval foundation.

Only reviewed, active, locale-compatible knowledge may be exposed to the
patient-facing dental conversation layer. This module is intentionally
provider-neutral and does not perform diagnosis or treatment decisions.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .dental_conversation import DentalKnowledgeEntry, DentalKnowledgeRetriever, DentalTopic


@dataclass(frozen=True, slots=True)
class CuratedDentalKnowledgeRecord:
    entry: DentalKnowledgeEntry
    active: bool = True
    clinically_reviewed: bool = False
    approved_for_patient_education: bool = False

    @property
    def eligible_for_patient_agent(self) -> bool:
        return (
            self.active
            and self.clinically_reviewed
            and self.approved_for_patient_education
            and bool(self.entry.reviewed_by)
        )


class CuratedDentalKnowledgeRetriever(DentalKnowledgeRetriever):
    """Simple deterministic retriever over an approved knowledge collection.

    This is the domain contract used before a production vector store is wired in.
    It enforces approval and locale/topic boundaries first, then performs a small
    lexical ranking so unreviewed material can never enter model context.
    """

    def __init__(self, records: Iterable[CuratedDentalKnowledgeRecord]) -> None:
        self._records = tuple(records)

    async def search(
        self,
        *,
        query: str,
        locale: str,
        topic: DentalTopic | None,
        limit: int = 5,
    ) -> Sequence[DentalKnowledgeEntry]:
        normalized_query = query.casefold().strip()
        terms = {term for term in normalized_query.split() if len(term) >= 3}

        candidates: list[tuple[int, DentalKnowledgeEntry]] = []
        for record in self._records:
            entry = record.entry
            if not record.eligible_for_patient_agent:
                continue
            if entry.locale.casefold() != locale.casefold():
                continue
            if topic is not None and entry.topic != topic:
                continue

            haystack = f"{entry.title} {entry.content}".casefold()
            score = sum(1 for term in terms if term in haystack)
            if terms and score == 0:
                continue
            candidates.append((score, entry))

        candidates.sort(key=lambda item: (-item[0], item[1].title.casefold(), item[1].entry_id))
        return tuple(entry for _, entry in candidates[: max(0, limit)])
