from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DentalKnowledgeReviewDecision(BaseModel):
    decision_note: str | None = Field(default=None, max_length=4000)


class DentalKnowledgeRejectDecision(BaseModel):
    decision_note: str = Field(min_length=1, max_length=4000)


class DentalKnowledgeReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    clinic_id: UUID
    entry_key: str
    version: int
    topic: str
    locale: str
    title: str
    source_name: str
    source_reference: str
    review_status: Literal["draft", "in_review", "approved", "rejected"]
    active: bool
    clinically_reviewed: bool
    approved_for_patient_education: bool
    submitted_by: UUID | None = None
    submitted_at: datetime | None = None
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    decision_note: str | None = None
    retired_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
