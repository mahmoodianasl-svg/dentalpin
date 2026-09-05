from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.patient_agent.dental_knowledge_review_service import (
    DentalKnowledgeReviewService,
)
from app.modules.patient_agent.models import PatientAgentAuditEvent


def _record(*, status: str = "draft", clinic_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        clinic_id=clinic_id or uuid.uuid4(),
        entry_key="implant-basics",
        version=1,
        review_status=status,
        submitted_by=None,
        submitted_at=None,
        reviewed_by=None,
        reviewed_at=None,
        decision_note=None,
        clinically_reviewed=False,
        approved_for_patient_education=False,
        active=True,
        retired_at=None,
    )


def _db_for(record):
    result = SimpleNamespace(scalar_one_or_none=lambda: record)
    return SimpleNamespace(
        execute=AsyncMock(return_value=result),
        add=lambda value: added.append(value),
        flush=AsyncMock(),
    )


added = []


@pytest.fixture(autouse=True)
def _clear_added():
    added.clear()


async def test_submit_records_actor_and_clears_prior_review_metadata() -> None:
    record = _record(status="rejected")
    record.reviewed_by = uuid.uuid4()
    record.decision_note = "needs revision"
    db = _db_for(record)
    actor = uuid.uuid4()

    result = await DentalKnowledgeReviewService().submit(
        db=db,
        clinic_id=record.clinic_id,
        record_id=record.id,
        actor_user_id=actor,
    )

    assert result.review_status == "in_review"
    assert result.submitted_by == actor
    assert result.submitted_at is not None
    assert result.reviewed_by is None
    assert result.decision_note is None
    assert any(isinstance(item, PatientAgentAuditEvent) for item in added)


async def test_approve_sets_named_reviewer_and_patient_education_flags() -> None:
    record = _record(status="in_review")
    db = _db_for(record)
    actor = uuid.uuid4()

    result = await DentalKnowledgeReviewService().approve(
        db=db,
        clinic_id=record.clinic_id,
        record_id=record.id,
        actor_user_id=actor,
        decision_note="Reviewed for patient education",
    )

    assert result.review_status == "approved"
    assert result.reviewed_by == actor
    assert result.reviewed_at is not None
    assert result.clinically_reviewed is True
    assert result.approved_for_patient_education is True


async def test_reject_requires_reason_and_clears_approval_flags() -> None:
    record = _record(status="in_review")
    record.clinically_reviewed = True
    record.approved_for_patient_education = True
    db = _db_for(record)

    with pytest.raises(ValueError, match="Rejection reason"):
        await DentalKnowledgeReviewService().reject(
            db=db,
            clinic_id=record.clinic_id,
            record_id=record.id,
            actor_user_id=uuid.uuid4(),
            decision_note="   ",
        )

    result = await DentalKnowledgeReviewService().reject(
        db=db,
        clinic_id=record.clinic_id,
        record_id=record.id,
        actor_user_id=uuid.uuid4(),
        decision_note="Source needs clarification",
    )
    assert result.review_status == "rejected"
    assert result.clinically_reviewed is False
    assert result.approved_for_patient_education is False


async def test_invalid_state_transition_is_rejected() -> None:
    record = _record(status="approved")
    db = _db_for(record)

    with pytest.raises(ValueError, match="Only draft or rejected"):
        await DentalKnowledgeReviewService().submit(
            db=db,
            clinic_id=record.clinic_id,
            record_id=record.id,
            actor_user_id=uuid.uuid4(),
        )


async def test_missing_or_cross_clinic_record_is_not_exposed() -> None:
    db = _db_for(None)

    with pytest.raises(LookupError, match="not found"):
        await DentalKnowledgeReviewService().approve(
            db=db,
            clinic_id=uuid.uuid4(),
            record_id=uuid.uuid4(),
            actor_user_id=uuid.uuid4(),
        )
