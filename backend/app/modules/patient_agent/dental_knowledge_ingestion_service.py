from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .dental_knowledge_ingestion_schemas import (
    DentalKnowledgeCorpusEntry,
    DentalKnowledgeCorpusImportRequest,
)
from .dental_knowledge_locks import (
    dental_knowledge_lock_key,
    lock_dental_knowledge_entries,
)
from .models import PatientAgentAuditEvent, PatientAgentDentalKnowledge
from .semantic_embeddings import SEMANTIC_EMBEDDING_KEY


@dataclass(frozen=True, slots=True)
class DentalKnowledgeCorpusImportResult:
    corpus_id: str
    corpus_version: str
    created: tuple[PatientAgentDentalKnowledge, ...]
    skipped: tuple[PatientAgentDentalKnowledge, ...]


class DentalKnowledgeCorpusIngestionService:
    """Create clinic-scoped draft knowledge versions from a curated corpus payload."""

    async def ingest(
        self,
        *,
        db: AsyncSession,
        clinic_id: UUID,
        actor_user_id: UUID,
        payload: DentalKnowledgeCorpusImportRequest,
    ) -> DentalKnowledgeCorpusImportResult:
        self._ensure_unique_entry_keys(payload)
        await self._lock_entry_keys(
            db=db,
            clinic_id=clinic_id,
            entry_keys=(entry.entry_key for entry in payload.entries),
        )

        created: list[PatientAgentDentalKnowledge] = []
        skipped: list[PatientAgentDentalKnowledge] = []
        for entry in payload.entries:
            latest = await self._latest_record(
                db=db,
                clinic_id=clinic_id,
                entry_key=entry.entry_key,
            )
            fingerprint = self._fingerprint(entry)
            if latest is not None and self._record_fingerprint(latest) == fingerprint:
                skipped.append(latest)
                db.add(
                    self._audit(
                        clinic_id=clinic_id,
                        actor_user_id=actor_user_id,
                        record=latest,
                        event_type="dental_knowledge_corpus_entry_skipped",
                        outcome="unchanged",
                        corpus_id=payload.corpus_id,
                        corpus_version=payload.corpus_version,
                        fingerprint=fingerprint,
                    )
                )
                continue

            version = 1 if latest is None else latest.version + 1
            metadata = self._safe_source_metadata(entry.source_metadata)
            metadata["ingestion"] = {
                "corpus_id": payload.corpus_id,
                "corpus_version": payload.corpus_version,
                "content_sha256": fingerprint,
            }
            record = PatientAgentDentalKnowledge(
                clinic_id=clinic_id,
                entry_key=entry.entry_key,
                version=version,
                topic=entry.topic.value,
                locale=entry.locale,
                title=entry.title.strip(),
                content=entry.content.strip(),
                source_name=entry.source_name.strip(),
                source_reference=entry.source_reference.strip(),
                source_metadata=metadata,
                review_status="draft",
                active=False,
                clinically_reviewed=False,
                approved_for_patient_education=False,
                submitted_by=None,
                submitted_at=None,
                reviewed_by=None,
                reviewed_at=None,
                decision_note=None,
                retired_at=None,
            )
            db.add(record)
            await db.flush()
            db.add(
                self._audit(
                    clinic_id=clinic_id,
                    actor_user_id=actor_user_id,
                    record=record,
                    event_type="dental_knowledge_corpus_entry_ingested",
                    outcome="created",
                    corpus_id=payload.corpus_id,
                    corpus_version=payload.corpus_version,
                    fingerprint=fingerprint,
                )
            )
            created.append(record)

        await db.flush()
        return DentalKnowledgeCorpusImportResult(
            corpus_id=payload.corpus_id,
            corpus_version=payload.corpus_version,
            created=tuple(created),
            skipped=tuple(skipped),
        )

    @staticmethod
    def _ensure_unique_entry_keys(payload: DentalKnowledgeCorpusImportRequest) -> None:
        seen: set[str] = set()
        duplicate_keys: set[str] = set()
        for entry in payload.entries:
            if entry.entry_key in seen:
                duplicate_keys.add(entry.entry_key)
            seen.add(entry.entry_key)
        if duplicate_keys:
            joined = ", ".join(sorted(duplicate_keys))
            raise ValueError(f"Duplicate corpus entry_key values: {joined}")

    @staticmethod
    async def _lock_entry_keys(
        *,
        db: AsyncSession,
        clinic_id: UUID,
        entry_keys: Iterable[str],
    ) -> None:
        """Serialize version allocation without creating persistent lock rows.

        PostgreSQL transaction-level advisory locks are held through the request
        commit/rollback boundary. Sorting prevents two overlapping batches from
        acquiring the same keys in opposite order and deadlocking.
        """
        await lock_dental_knowledge_entries(
            db=db,
            clinic_id=clinic_id,
            entry_keys=entry_keys,
        )

    @staticmethod
    def _lock_key(*, clinic_id: UUID, entry_key: str) -> int:
        return dental_knowledge_lock_key(clinic_id=clinic_id, entry_key=entry_key)

    @staticmethod
    async def _latest_record(
        *,
        db: AsyncSession,
        clinic_id: UUID,
        entry_key: str,
    ) -> PatientAgentDentalKnowledge | None:
        result = await db.execute(
            select(PatientAgentDentalKnowledge)
            .where(
                PatientAgentDentalKnowledge.clinic_id == clinic_id,
                PatientAgentDentalKnowledge.entry_key == entry_key,
            )
            .order_by(PatientAgentDentalKnowledge.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @classmethod
    def _record_fingerprint(cls, record: PatientAgentDentalKnowledge) -> str:
        metadata = record.source_metadata or {}
        ingestion = metadata.get("ingestion") if isinstance(metadata, dict) else None
        if isinstance(ingestion, dict):
            value = ingestion.get("content_sha256")
            if isinstance(value, str) and len(value) == 64:
                return value
        return cls._fingerprint_values(
            topic=record.topic,
            locale=record.locale,
            title=record.title,
            content=record.content,
            source_name=record.source_name,
            source_reference=record.source_reference,
            source_metadata=cls._safe_source_metadata(metadata),
        )

    @classmethod
    def _fingerprint(cls, entry: DentalKnowledgeCorpusEntry) -> str:
        return cls._fingerprint_values(
            topic=entry.topic.value,
            locale=entry.locale,
            title=entry.title,
            content=entry.content,
            source_name=entry.source_name,
            source_reference=entry.source_reference,
            source_metadata=cls._safe_source_metadata(entry.source_metadata),
        )

    @staticmethod
    def _fingerprint_values(
        *,
        topic: str,
        locale: str,
        title: str,
        content: str,
        source_name: str,
        source_reference: str,
        source_metadata: dict[str, object],
    ) -> str:
        canonical = json.dumps(
            {
                "topic": topic,
                "locale": locale.strip(),
                "title": title.strip(),
                "content": content.strip(),
                "source_name": source_name.strip(),
                "source_reference": source_reference.strip(),
                "source_metadata": source_metadata,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _safe_source_metadata(metadata: object) -> dict[str, object]:
        if not isinstance(metadata, dict):
            return {}
        return {
            str(key): value
            for key, value in metadata.items()
            if key not in {SEMANTIC_EMBEDDING_KEY, "ingestion"}
        }

    @staticmethod
    def _audit(
        *,
        clinic_id: UUID,
        actor_user_id: UUID,
        record: PatientAgentDentalKnowledge,
        event_type: str,
        outcome: str,
        corpus_id: str,
        corpus_version: str,
        fingerprint: str,
    ) -> PatientAgentAuditEvent:
        return PatientAgentAuditEvent(
            session_id=None,
            clinic_id=clinic_id,
            patient_id=None,
            event_type=event_type,
            actor_type="staff",
            outcome=outcome,
            detail={
                "actor_user_id": str(actor_user_id),
                "knowledge_id": str(record.id),
                "entry_key": record.entry_key,
                "version": record.version,
                "review_status": record.review_status,
                "corpus_id": corpus_id,
                "corpus_version": corpus_version,
                "content_sha256": fingerprint,
            },
            reason=None,
        )
