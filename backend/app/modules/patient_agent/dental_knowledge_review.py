"""Dentist review workflow for curated patient-education knowledge.

The workflow is deliberately domain-only and audit-friendly. It controls
review state and approval metadata; it does not publish directly to a vector
store or grant autonomous clinical authority to the patient agent.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum

from .dental_knowledge import CuratedDentalKnowledgeRecord


class DentalKnowledgeReviewStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class DentalKnowledgeReview:
    record: CuratedDentalKnowledgeRecord
    status: DentalKnowledgeReviewStatus = DentalKnowledgeReviewStatus.DRAFT
    submitted_by: str | None = None
    submitted_at: datetime | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    decision_note: str | None = None

    @property
    def patient_agent_eligible(self) -> bool:
        return (
            self.status is DentalKnowledgeReviewStatus.APPROVED
            and self.record.eligible_for_patient_agent
        )


class DentalKnowledgeReviewWorkflow:
    """Deterministic state transitions for dentist-reviewed knowledge."""

    @staticmethod
    def submit(review: DentalKnowledgeReview, *, submitted_by: str) -> DentalKnowledgeReview:
        if review.status not in {
            DentalKnowledgeReviewStatus.DRAFT,
            DentalKnowledgeReviewStatus.REJECTED,
        }:
            raise ValueError("Only draft or rejected knowledge can be submitted for review")
        if not submitted_by.strip():
            raise ValueError("submitted_by is required")
        return replace(
            review,
            status=DentalKnowledgeReviewStatus.IN_REVIEW,
            submitted_by=submitted_by,
            submitted_at=datetime.now(timezone.utc),
            reviewed_by=None,
            reviewed_at=None,
            decision_note=None,
        )

    @staticmethod
    def approve(
        review: DentalKnowledgeReview,
        *,
        dentist_id: str,
        decision_note: str | None = None,
    ) -> DentalKnowledgeReview:
        if review.status is not DentalKnowledgeReviewStatus.IN_REVIEW:
            raise ValueError("Knowledge must be in review before approval")
        if not dentist_id.strip():
            raise ValueError("dentist_id is required")
        approved_record = replace(
            review.record,
            clinically_reviewed=True,
            approved_for_patient_education=True,
            entry=replace(review.record.entry, reviewed_by=dentist_id),
        )
        return replace(
            review,
            record=approved_record,
            status=DentalKnowledgeReviewStatus.APPROVED,
            reviewed_by=dentist_id,
            reviewed_at=datetime.now(timezone.utc),
            decision_note=decision_note,
        )

    @staticmethod
    def reject(
        review: DentalKnowledgeReview,
        *,
        dentist_id: str,
        decision_note: str,
    ) -> DentalKnowledgeReview:
        if review.status is not DentalKnowledgeReviewStatus.IN_REVIEW:
            raise ValueError("Knowledge must be in review before rejection")
        if not dentist_id.strip():
            raise ValueError("dentist_id is required")
        if not decision_note.strip():
            raise ValueError("decision_note is required when rejecting knowledge")
        rejected_record = replace(
            review.record,
            clinically_reviewed=False,
            approved_for_patient_education=False,
            entry=replace(review.record.entry, reviewed_by=None),
        )
        return replace(
            review,
            record=rejected_record,
            status=DentalKnowledgeReviewStatus.REJECTED,
            reviewed_by=dentist_id,
            reviewed_at=datetime.now(timezone.utc),
            decision_note=decision_note,
        )
