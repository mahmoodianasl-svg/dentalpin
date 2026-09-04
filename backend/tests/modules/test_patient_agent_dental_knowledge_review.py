from __future__ import annotations

import pytest

from app.modules.patient_agent.dental_conversation import DentalKnowledgeEntry, DentalTopic
from app.modules.patient_agent.dental_knowledge import CuratedDentalKnowledgeRecord
from app.modules.patient_agent.dental_knowledge_review import (
    DentalKnowledgeReview,
    DentalKnowledgeReviewStatus,
    DentalKnowledgeReviewWorkflow,
)


def _review() -> DentalKnowledgeReview:
    entry = DentalKnowledgeEntry(
        entry_id="implant-guide",
        topic=DentalTopic.IMPLANTS,
        title="Dental implant guide",
        content="General patient education about dental implants.",
        source_name="Clinic draft knowledge",
        source_reference="kb://implant-guide",
        reviewed_by=None,
        locale="en",
    )
    return DentalKnowledgeReview(record=CuratedDentalKnowledgeRecord(entry=entry))


def test_submit_moves_draft_to_in_review_and_records_submitter() -> None:
    submitted = DentalKnowledgeReviewWorkflow.submit(_review(), submitted_by="author-1")

    assert submitted.status is DentalKnowledgeReviewStatus.IN_REVIEW
    assert submitted.submitted_by == "author-1"
    assert submitted.submitted_at is not None
    assert submitted.reviewed_by is None
    assert not submitted.patient_agent_eligible


def test_approve_requires_in_review_and_makes_record_eligible() -> None:
    submitted = DentalKnowledgeReviewWorkflow.submit(_review(), submitted_by="author-1")
    approved = DentalKnowledgeReviewWorkflow.approve(
        submitted,
        dentist_id="dentist-7",
        decision_note="Clinically reviewed for patient education.",
    )

    assert approved.status is DentalKnowledgeReviewStatus.APPROVED
    assert approved.reviewed_by == "dentist-7"
    assert approved.reviewed_at is not None
    assert approved.record.clinically_reviewed
    assert approved.record.approved_for_patient_education
    assert approved.record.entry.reviewed_by == "dentist-7"
    assert approved.patient_agent_eligible


def test_reject_clears_patient_education_approval_and_requires_reason() -> None:
    submitted = DentalKnowledgeReviewWorkflow.submit(_review(), submitted_by="author-1")
    rejected = DentalKnowledgeReviewWorkflow.reject(
        submitted,
        dentist_id="dentist-7",
        decision_note="Needs clearer contraindication language.",
    )

    assert rejected.status is DentalKnowledgeReviewStatus.REJECTED
    assert rejected.reviewed_by == "dentist-7"
    assert rejected.reviewed_at is not None
    assert not rejected.record.clinically_reviewed
    assert not rejected.record.approved_for_patient_education
    assert rejected.record.entry.reviewed_by is None
    assert not rejected.patient_agent_eligible

    with pytest.raises(ValueError, match="decision_note"):
        DentalKnowledgeReviewWorkflow.reject(
            submitted,
            dentist_id="dentist-7",
            decision_note=" ",
        )


def test_cannot_approve_or_reject_without_review_submission() -> None:
    review = _review()

    with pytest.raises(ValueError, match="in review"):
        DentalKnowledgeReviewWorkflow.approve(review, dentist_id="dentist-7")

    with pytest.raises(ValueError, match="in review"):
        DentalKnowledgeReviewWorkflow.reject(
            review,
            dentist_id="dentist-7",
            decision_note="Not ready.",
        )


def test_rejected_knowledge_can_be_resubmitted_but_approved_cannot() -> None:
    submitted = DentalKnowledgeReviewWorkflow.submit(_review(), submitted_by="author-1")
    rejected = DentalKnowledgeReviewWorkflow.reject(
        submitted,
        dentist_id="dentist-7",
        decision_note="Revise wording.",
    )
    resubmitted = DentalKnowledgeReviewWorkflow.submit(rejected, submitted_by="author-2")

    assert resubmitted.status is DentalKnowledgeReviewStatus.IN_REVIEW
    assert resubmitted.submitted_by == "author-2"
    assert resubmitted.reviewed_by is None
    assert resubmitted.reviewed_at is None
    assert resubmitted.decision_note is None
    assert not resubmitted.patient_agent_eligible

    approved = DentalKnowledgeReviewWorkflow.approve(resubmitted, dentist_id="dentist-8")
    with pytest.raises(ValueError, match="draft or rejected"):
        DentalKnowledgeReviewWorkflow.submit(approved, submitted_by="author-3")
