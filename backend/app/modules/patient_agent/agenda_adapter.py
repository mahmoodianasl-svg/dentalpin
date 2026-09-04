"""Patient-scoped appointment adapter backed by DentalPin agenda/schedules services."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agenda.models import Appointment
from app.modules.agenda.service import AppointmentService
from app.modules.agenda.tz import as_utc, get_clinic_tz
from app.modules.schedules.services.availability import AvailabilityService

from .confirmation import decode_appointment_confirmation_token
from .models import PatientAgentAppointmentProposal, PatientAgentAuditEvent
from .tools import AppointmentSlot

_BLOCKING_STATUSES = {"scheduled", "confirmed", "checked_in", "in_treatment"}


class DentalPinPatientAppointmentAdapter:
    """Narrow adapter for patient-visible scheduling operations.

    Reads are clinic-scoped. Writes additionally bind the appointment to the
    authenticated patient and require a persisted, server-signed one-time
    confirmation proposal.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def normalize_slot(self, *, clinic_id: UUID, slot: AppointmentSlot) -> AppointmentSlot:
        tz = await get_clinic_tz(self.db, clinic_id)
        return AppointmentSlot(
            professional_id=slot.professional_id,
            starts_at=as_utc(slot.starts_at, tz),
            ends_at=as_utc(slot.ends_at, tz),
        )

    async def validate_slot_available(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        slot: AppointmentSlot,
    ) -> AppointmentSlot:
        """Return a UTC-normalized slot only when it is open and conflict-free."""
        slot = await self.normalize_slot(clinic_id=clinic_id, slot=slot)
        if slot.ends_at <= slot.starts_at:
            raise ValueError("Invalid appointment slot")
        if not await AppointmentService.validate_patient_access(self.db, clinic_id, patient_id):
            raise PermissionError("Patient not found")
        if not await AppointmentService.validate_professional_access(
            self.db, clinic_id, slot.professional_id
        ):
            raise ValueError("Professional not found")

        tz = await get_clinic_tz(self.db, clinic_id)
        local_start = slot.starts_at.astimezone(tz)
        local_end = slot.ends_at.astimezone(tz)
        _tz_name, ranges = await AvailabilityService.resolve(
            self.db,
            clinic_id,
            local_start.date(),
            local_end.date(),
            slot.professional_id,
        )
        within_open_hours = any(
            item.state == "open" and item.start <= slot.starts_at and slot.ends_at <= item.end
            for item in ranges
        )
        if not within_open_hours:
            raise ValueError("Selected appointment slot is outside available hours")

        conflict = await self.db.execute(
            select(Appointment.id)
            .where(
                Appointment.clinic_id == clinic_id,
                Appointment.professional_id == slot.professional_id,
                Appointment.status.in_(_BLOCKING_STATUSES),
                Appointment.start_time < slot.ends_at,
                Appointment.end_time > slot.starts_at,
            )
            .limit(1)
        )
        if conflict.scalar_one_or_none() is not None:
            raise ValueError("Selected appointment slot is no longer available")
        return slot

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

        tz = await get_clinic_tz(self.db, clinic_id)
        starts_after = as_utc(starts_after, tz)
        ends_before = as_utc(ends_before, tz)
        if ends_before <= starts_after:
            raise ValueError("Invalid time range")
        local_start = starts_after.astimezone(tz)
        local_end = ends_before.astimezone(tz)
        _tz_name, ranges = await AvailabilityService.resolve(
            self.db,
            clinic_id,
            local_start.date(),
            local_end.date(),
            professional_id,
        )
        open_ranges = sorted((r.start, r.end) for r in ranges if r.state == "open")
        if not open_ranges:
            return []

        appointments, _ = await AppointmentService.list_appointments(
            self.db,
            clinic_id,
            start_date=starts_after - timedelta(days=1),
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
                if not overlapping and professional_id is not None:
                    slots.append(
                        AppointmentSlot(
                            professional_id=professional_id,
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
        slot = await self.normalize_slot(clinic_id=clinic_id, slot=slot)
        if claims.get("professional_id") != str(slot.professional_id):
            raise PermissionError("Confirmation token does not match professional")
        if (
            claims.get("starts_at") != slot.starts_at.isoformat()
            or claims.get("ends_at") != slot.ends_at.isoformat()
        ):
            raise PermissionError("Confirmation token does not match appointment slot")

        result = await self.db.execute(
            select(PatientAgentAppointmentProposal)
            .where(
                PatientAgentAppointmentProposal.jti == claims["jti"],
                PatientAgentAppointmentProposal.clinic_id == clinic_id,
                PatientAgentAppointmentProposal.patient_id == patient_id,
            )
            .with_for_update()
        )
        proposal = result.scalar_one_or_none()
        if proposal is None:
            raise ValueError("Appointment confirmation proposal not found")
        if proposal.consumed_at is not None:
            raise ValueError("Appointment confirmation has already been used")
        now = datetime.now(UTC)
        if proposal.expires_at <= now:
            raise ValueError("Appointment confirmation proposal has expired")
        if (
            proposal.professional_id != slot.professional_id
            or proposal.starts_at != slot.starts_at
            or proposal.ends_at != slot.ends_at
        ):
            raise PermissionError("Confirmation proposal does not match appointment slot")

        slot = await self.validate_slot_available(
            clinic_id=clinic_id,
            patient_id=patient_id,
            slot=slot,
        )
        proposal.consumed_at = now

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
            self.db.add(
                PatientAgentAuditEvent(
                    session_id=None,
                    clinic_id=clinic_id,
                    patient_id=patient_id,
                    event_type="appointment_confirmation_consumed",
                    actor_type="patient",
                    outcome="success",
                    detail={
                        "appointment_id": str(appointment.id),
                        "proposal_jti": proposal.jti,
                        "professional_id": str(slot.professional_id),
                        "starts_at": slot.starts_at.isoformat(),
                        "ends_at": slot.ends_at.isoformat(),
                    },
                )
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
