from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class StaffHandoffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: UUID
    patient_id: UUID | None
    channel: str
    handoff_state: Literal["requested", "emergency_escalation", "accepted"]
    urgency: str | None = None
    summary: str | None = None
    accepted_by: UUID | None = None
    accepted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
