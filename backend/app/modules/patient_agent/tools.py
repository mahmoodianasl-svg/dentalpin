"""Patient-safe tool contracts used by the realtime agent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class AppointmentSlot:
    professional_id: UUID
    starts_at: datetime
    ends_at: datetime


class PatientAppointmentTools(Protocol):
    """Narrow appointment surface exposed to the patient agent.

    Implementations must enforce clinic/patient scope independently of model
    output. Mutation methods require a server-validated confirmation token.
    """

    async def search_available_slots(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        starts_after: datetime,
        ends_before: datetime,
        professional_id: UUID | None = None,
    ) -> list[AppointmentSlot]: ...

    async def create_appointment(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        slot: AppointmentSlot,
        confirmation_token: str,
    ) -> UUID: ...

    async def request_human_handoff(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        reason: str,
        urgency: str,
    ) -> None: ...
