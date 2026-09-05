"""Clinic-scoped staff workflow for persistent dental knowledge review."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import PatientAgentAuditEvent, PatientAgentDentalKnowledge


class DentalKnowledgeReviewService:
    """Apply auditable review transitions within one clinic boundary."""

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
        record = await self._require_record(db=db, clinic_id=clinic_id, record_id=record_id)
        if record.review_status != "in_review":
            raise ValueError("Only in-review knowledge can be approved")

        record.review_status = "approved"
        record.reviewed_by = actor_user_id
        record.reviewed_at = datetime.now(UTC)
        record.decision_note = decision_note.strip() if decision_note else None
        record.clinically_reviewed = True
        record.approved_for_patient_education = True
        record.active = True
        record.retired_at = None
        db.add(self._audit(record, actor_user_id, "dental_knowledge_approved", "success"))
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
    ) -> PatientAgentAuditEvent:
        return PatientAgentAuditEvent(
            session_id=None,
            clinic_id=record.clinic_id,
            patient_id=None,
            event_type=event_type,
            actor_type="staff",
            outcome=outcome,
            detail={
                "knowledge_id": str(record.id),
                "entry_key": record.entry_key,
                "version": record.version,
                "review_status": record.review_status,
                "actor_user_id": str(actor_user_id),
            },
            reason=reason,
        )
