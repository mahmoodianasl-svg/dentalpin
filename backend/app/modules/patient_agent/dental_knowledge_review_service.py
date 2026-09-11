"""Clinic-scoped staff workflow for persistent dental knowledge review."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .dental_knowledge_locks import lock_dental_knowledge_entries
from .models import PatientAgentAuditEvent, PatientAgentDentalKnowledge
from .semantic_embeddings import (
    EmbeddingProvider,
    configured_embedding_provider,
    semantic_embedding_input,
    with_semantic_embedding,
    without_semantic_embedding,
)


class DentalKnowledgeReviewService:
    """Apply auditable review transitions within one clinic boundary."""

    def __init__(self, *, embedding_provider: EmbeddingProvider | None = None) -> None:
        self._embedding_provider = embedding_provider or configured_embedding_provider()

    async def get_record(
        self,
        *,
        db: AsyncSession,
        clinic_id: UUID,
        record_id: UUID,
    ) -> PatientAgentDentalKnowledge | None:
        result = await db.execute(
            select(PatientAgentDentalKnowledge).where(
                PatientAgentDentalKnowledge.id == record_id,
                PatientAgentDentalKnowledge.clinic_id == clinic_id,
            )
        )
        return result.scalar_one_or_none()

    async def submit(
        self,
        *,
        db: AsyncSession,
        clinic_id: UUID,
        record_id: UUID,
        actor_user_id: UUID,
    ) -> PatientAgentDentalKnowledge:
        record = await self._require_record(db=db, clinic_id=clinic_id, record_id=record_id)
        if record.review_status not in {"draft", "rejected"}:
            raise ValueError("Only draft or rejected knowledge can be submitted")

        record.review_status = "in_review"
        record.submitted_by = actor_user_id
        record.submitted_at = datetime.now(UTC)
        record.reviewed_by = None
        record.reviewed_at = None
        record.decision_note = None
        record.clinically_reviewed = False
        record.approved_for_patient_education = False
        record.source_metadata = without_semantic_embedding(
            getattr(record, "source_metadata", None)
        )
        db.add(self._audit(record, actor_user_id, "dental_knowledge_submitted", "recorded"))
        await db.flush()
        return record

    async def approve(
        self,
        *,
        db: AsyncSession,
        clinic_id: UUID,
        record_id: UUID,
        actor_user_id: UUID,
        decision_note: str | None = None,
    ) -> PatientAgentDentalKnowledge:
        candidate = await self._require_record(
            db=db,
            clinic_id=clinic_id,
            record_id=record_id,
        )
        await lock_dental_knowledge_entries(
            db=db,
            clinic_id=clinic_id,
            entry_keys=[candidate.entry_key],
        )
        record = await self._require_record(db=db, clinic_id=clinic_id, record_id=record_id)
        if record.review_status != "in_review":
            raise ValueError("Only in-review knowledge can be approved")

        active_versions = await self._active_approved_versions(
            db=db,
            clinic_id=clinic_id,
            entry_key=record.entry_key,
            excluding_id=record.id,
        )
        if any(existing.version >= record.version for existing in active_versions):
            raise ValueError("An equal or newer knowledge version is already active")

        reviewed_at = datetime.now(UTC)
        for existing in active_versions:
            self._retire_record(existing, retired_at=reviewed_at)
            db.add(
                self._audit(
                    existing,
                    actor_user_id,
                    "dental_knowledge_superseded",
                    "success",
                    reason="Superseded by a newer approved version",
                    replacement=record,
                )
            )

        record.review_status = "approved"
        record.reviewed_by = actor_user_id
        record.reviewed_at = reviewed_at
        record.decision_note = decision_note.strip() if decision_note else None
        record.clinically_reviewed = True
        record.approved_for_patient_education = True
        record.active = True
        record.retired_at = None
        indexed = await self._refresh_semantic_embedding(record)
        db.add(
            self._audit(
                record,
                actor_user_id,
                "dental_knowledge_approved",
                "success",
                semantic_indexed=indexed,
            )
        )
        await db.flush()
        return record

    async def retire(
        self,
        *,
        db: AsyncSession,
        clinic_id: UUID,
        record_id: UUID,
        actor_user_id: UUID,
        reason: str,
    ) -> PatientAgentDentalKnowledge:
        retirement_reason = reason.strip()
        if not retirement_reason:
            raise ValueError("Retirement reason is required")

        candidate = await self._require_record(
            db=db,
            clinic_id=clinic_id,
            record_id=record_id,
        )
        await lock_dental_knowledge_entries(
            db=db,
            clinic_id=clinic_id,
            entry_keys=[candidate.entry_key],
        )
        record = await self._require_record(db=db, clinic_id=clinic_id, record_id=record_id)
        if not self._eligible_for_semantic_index(record):
            raise ValueError("Only active approved patient-education knowledge can be retired")

        self._retire_record(record, retired_at=datetime.now(UTC))
        db.add(
            self._audit(
                record,
                actor_user_id,
                "dental_knowledge_retired",
                "success",
                reason=retirement_reason,
            )
        )
        await db.flush()
        return record

    async def reject(
        self,
        *,
        db: AsyncSession,
        clinic_id: UUID,
        record_id: UUID,
        actor_user_id: UUID,
        decision_note: str,
    ) -> PatientAgentDentalKnowledge:
        reason = decision_note.strip()
        if not reason:
            raise ValueError("Rejection reason is required")

        record = await self._require_record(db=db, clinic_id=clinic_id, record_id=record_id)
        if record.review_status != "in_review":
            raise ValueError("Only in-review knowledge can be rejected")

        record.review_status = "rejected"
        record.reviewed_by = actor_user_id
        record.reviewed_at = datetime.now(UTC)
        record.decision_note = reason
        record.clinically_reviewed = False
        record.approved_for_patient_education = False
        record.source_metadata = without_semantic_embedding(
            getattr(record, "source_metadata", None)
        )
        db.add(
            self._audit(
                record,
                actor_user_id,
                "dental_knowledge_rejected",
                "recorded",
                reason=reason,
            )
        )
        await db.flush()
        return record

    async def reindex(
        self,
        *,
        db: AsyncSession,
        clinic_id: UUID,
        record_id: UUID,
        actor_user_id: UUID,
    ) -> PatientAgentDentalKnowledge:
        record = await self._require_record(db=db, clinic_id=clinic_id, record_id=record_id)
        if not self._eligible_for_semantic_index(record):
            raise ValueError("Only active approved patient-education knowledge can be reindexed")
        provider = self._embedding_provider
        if provider is None:
            raise ValueError("Semantic embedding provider is not configured")

        try:
            vector = await provider.embed(
                semantic_embedding_input(title=record.title, content=record.content)
            )
            record.source_metadata = with_semantic_embedding(
                getattr(record, "source_metadata", None),
                model=provider.model,
                vector=vector,
                title=record.title,
                content=record.content,
            )
        except Exception as exc:
            record.source_metadata = without_semantic_embedding(
                getattr(record, "source_metadata", None)
            )
            db.add(
                self._audit(
                    record,
                    actor_user_id,
                    "dental_knowledge_semantic_reindex_failed",
                    "failed",
                    reason=type(exc).__name__,
                    semantic_indexed=False,
                )
            )
            await db.flush()
            raise ValueError("Semantic reindex failed") from exc

        db.add(
            self._audit(
                record,
                actor_user_id,
                "dental_knowledge_semantic_reindexed",
                "success",
                semantic_indexed=True,
            )
        )
        await db.flush()
        return record

    async def _refresh_semantic_embedding(self, record: PatientAgentDentalKnowledge) -> bool:
        provider = self._embedding_provider
        record.source_metadata = without_semantic_embedding(
            getattr(record, "source_metadata", None)
        )
        if provider is None or not self._eligible_for_semantic_index(record):
            return False
        try:
            vector = await provider.embed(
                semantic_embedding_input(title=record.title, content=record.content)
            )
            record.source_metadata = with_semantic_embedding(
                record.source_metadata,
                model=provider.model,
                vector=vector,
                title=record.title,
                content=record.content,
            )
        except Exception:
            record.source_metadata = without_semantic_embedding(record.source_metadata)
            return False
        return True

    @staticmethod
    def _eligible_for_semantic_index(record: PatientAgentDentalKnowledge) -> bool:
        return (
            record.review_status == "approved"
            and record.active
            and record.clinically_reviewed
            and record.approved_for_patient_education
            and record.reviewed_by is not None
            and record.retired_at is None
        )

    @staticmethod
    async def _active_approved_versions(
        *,
        db: AsyncSession,
        clinic_id: UUID,
        entry_key: str,
        excluding_id: UUID,
    ) -> list[PatientAgentDentalKnowledge]:
        result = await db.execute(
            select(PatientAgentDentalKnowledge).where(
                PatientAgentDentalKnowledge.clinic_id == clinic_id,
                PatientAgentDentalKnowledge.entry_key == entry_key,
                PatientAgentDentalKnowledge.id != excluding_id,
                PatientAgentDentalKnowledge.review_status == "approved",
                PatientAgentDentalKnowledge.active.is_(True),
                PatientAgentDentalKnowledge.approved_for_patient_education.is_(True),
                PatientAgentDentalKnowledge.retired_at.is_(None),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    def _retire_record(
        record: PatientAgentDentalKnowledge,
        *,
        retired_at: datetime,
    ) -> None:
        record.active = False
        record.approved_for_patient_education = False
        record.retired_at = retired_at
        record.source_metadata = without_semantic_embedding(
            getattr(record, "source_metadata", None)
        )

    async def _require_record(
        self,
        *,
        db: AsyncSession,
        clinic_id: UUID,
        record_id: UUID,
    ) -> PatientAgentDentalKnowledge:
        record = await self.get_record(db=db, clinic_id=clinic_id, record_id=record_id)
        if record is None:
            raise LookupError("Dental knowledge record not found")
        return record

    @staticmethod
    def _audit(
        record: PatientAgentDentalKnowledge,
        actor_user_id: UUID,
        event_type: str,
        outcome: str,
        *,
        reason: str | None = None,
        semantic_indexed: bool | None = None,
        replacement: PatientAgentDentalKnowledge | None = None,
    ) -> PatientAgentAuditEvent:
        detail = {
            "knowledge_id": str(record.id),
            "entry_key": record.entry_key,
            "version": record.version,
            "review_status": record.review_status,
            "actor_user_id": str(actor_user_id),
        }
        if semantic_indexed is not None:
            detail["semantic_indexed"] = semantic_indexed
        if replacement is not None:
            detail["replacement_knowledge_id"] = str(replacement.id)
            detail["replacement_version"] = replacement.version
        return PatientAgentAuditEvent(
            session_id=None,
            clinic_id=record.clinic_id,
            patient_id=None,
            event_type=event_type,
            actor_type="staff",
            outcome=outcome,
            detail=detail,
            reason=reason,
        )
