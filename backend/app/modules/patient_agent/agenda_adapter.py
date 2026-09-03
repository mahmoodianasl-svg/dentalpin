"""Patient-scoped appointment adapter backed by DentalPin agenda/schedules services."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agenda.service import AppointmentService
from app.modules.schedules.services.availability import AvailabilityService

from .confirmation import decode_appointment_confirmation_token
from .tools import AppointmentSlot

_BLOCKING_STATUSES = {"scheduled", "confirmed", "checked_in", "in_treatment", "completed"}


class DentalPinPatientAppointmentAdapter:
    """Narrow adapter for patient-visible scheduling operations.

    Reads are clinic-scoped. Writes additionally bind the appointment to the
    authenticated patient and require a server-signed confirmation token.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def search_available_slots(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        starts_after: datetime,
        ends_before: datetime,
        professional_id: UUID | None = None,
    ) -> list[AppointmentSlot]:
        if not await AppointmentService.validate_patient_access(self.db, clinic_id, patient_id):
            raise PermissionError("Patient not found")
        if professional_id and not await AppointmentService.validate_professional_access(
            self.db, clinic_id, professional_id
        ):
            raise ValueError("Professional not found")

        start_day = starts_after.date()
        end_day = ends_before.date()
        _tz_name, ranges = await AvailabilityService.resolve(
            self.db, clinic_id, start_day, end_day, professional_id
        )
        open_ranges = sorted((r.start, r.end) for r in ranges if r.state == "open")
        if not open_ranges:
            return []

        appointments, _ = await AppointmentService.list_appointments(
            self.db,
            clinic_id,
            start_date=starts_after,
            end_date=ends_before,
            professional_id=professional_id,
            page_size=500,
        )
        busy = [
            (appt.start_time, appt.end_time, appt.professional_id)
            for appt in appointments
            if appt.status in _BLOCKING_STATUSES and appt.start_time and appt.end_time
        ]

        slots: list[AppointmentSlot] = []
        step = timedelta(minutes=30)
        for win_start, win_end in open_ranges:
            cursor = max(win_start, starts_after)
            boundary = min(win_end, ends_before)
            while cursor + step <= boundary:
                slot_end = cursor + step
                overlapping = [
                    item
                    for item in busy
                    if (professional_id is None or item[2] == professional_id)
                    and item[0] < slot_end
                    and item[1] > cursor
                ]
                if not overlapping:
                    slot_professional_id = professional_id
                    if slot_professional_id is not None:
                        slots.append(
                            AppointmentSlot(
                                professional_id=slot_professional_id,
                                starts_at=cursor,
                                ends_at=slot_end,
                            )
                        )
                cursor += step
        return slots[:20]

    async def create_appointment(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        slot: AppointmentSlot,
        confirmation_token: str,
    ) -> UUID:
        claims = decode_appointment_confirmation_token(
            confirmation_token,
            clinic_id=clinic_id,
            patient_id=patient_id,
        )
        if claims.get("professional_id") != str(slot.professional_id):
            raise PermissionError("Confirmation token does not match professional")
        if (
            claims.get("starts_at") != slot.starts_at.isoformat()
            or claims.get("ends_at") != slot.ends_at.isoformat()
        ):
            raise PermissionError("Confirmation token does not match appointment slot")
        if not await AppointmentService.validate_patient_access(self.db, clinic_id, patient_id):
            raise PermissionError("Patient not found")
        if not await AppointmentService.validate_professional_access(
            self.db, clinic_id, slot.professional_id
        ):
            raise ValueError("Professional not found")

        try:
            appointment = await AppointmentService.create_appointment(
                self.db,
                clinic_id,
                {
                    "patient_id": patient_id,
                    "professional_id": slot.professional_id,
                    "start_time": slot.starts_at,
                    "end_time": slot.ends_at,
                    "status": "scheduled",
                },
            )
            await AppointmentService.commit_and_publish_scheduled(self.db, appointment)
        except IntegrityError as exc:
            await self.db.rollback()
            raise ValueError("Selected appointment slot is no longer available") from exc
        return appointment.id

    async def request_human_handoff(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        reason: str,
        urgency: str,
    ) -> None:
        del clinic_id, patient_id, reason, urgency
        # Handoff persistence is owned by PatientAgentService; this method exists
        # only to satisfy the narrow tool protocol without creating a duplicate
        # notification channel in AI-1.
        return None
