"""Appointment range and overlap integrity regression coverage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership, User
from app.core.auth.service import hash_password
from app.modules.agenda.models import Appointment, Cabinet
from app.modules.agenda.service import AppointmentService
from app.modules.patients.models import Patient


async def _world(db: AsyncSession) -> dict[str, UUID]:
    clinic = Clinic(
        id=uuid4(),
        name="Overlap Clinic",
        tax_id=f"OV-{uuid4().hex[:12]}",
        address={"city": "Madrid"},
        settings={},
    )
    professional_a = User(
        id=uuid4(),
        email=f"overlap-a-{uuid4().hex[:8]}@test.clinic",
        password_hash=hash_password("TestPass1234"),
        first_name="Ada",
        last_name="Dentist",
        is_active=True,
    )
    professional_b = User(
        id=uuid4(),
        email=f"overlap-b-{uuid4().hex[:8]}@test.clinic",
        password_hash=hash_password("TestPass1234"),
        first_name="Ben",
        last_name="Dentist",
        is_active=True,
    )
    cabinet_a = Cabinet(
        id=uuid4(),
        clinic_id=clinic.id,
        name="A",
        color="#111111",
        display_order=0,
        is_active=True,
    )
    cabinet_b = Cabinet(
        id=uuid4(),
        clinic_id=clinic.id,
        name="B",
        color="#222222",
        display_order=1,
        is_active=True,
    )
    patient = Patient(
        id=uuid4(),
        clinic_id=clinic.id,
        first_name="Pat",
        last_name="Ient",
    )
    db.add_all([clinic, professional_a, professional_b, cabinet_a, cabinet_b, patient])
    await db.flush()
    db.add_all(
        [
            ClinicMembership(
                id=uuid4(),
                user_id=professional_a.id,
                clinic_id=clinic.id,
                role="dentist",
            ),
            ClinicMembership(
                id=uuid4(),
                user_id=professional_b.id,
                clinic_id=clinic.id,
                role="dentist",
            ),
        ]
    )
    await db.commit()
    return {
        "clinic": clinic.id,
        "professional_a": professional_a.id,
        "professional_b": professional_b.id,
        "cabinet_a": cabinet_a.id,
        "cabinet_b": cabinet_b.id,
        "patient": patient.id,
    }


async def _create(
    db: AsyncSession,
    world: dict[str, UUID],
    *,
    professional: UUID,
    cabinet: UUID | None,
    start: datetime,
    end: datetime,
    status: str = "scheduled",
) -> Appointment:
    appointment = await AppointmentService.create_appointment(
        db,
        world["clinic"],
        {
            "patient_id": world["patient"],
            "professional_id": professional,
            "cabinet_id": cabinet,
            "start_time": start,
            "end_time": end,
            "status": status,
        },
    )
    await db.commit()
    return appointment


@pytest.mark.asyncio
async def test_professional_cannot_overlap_across_cabinets(db_session: AsyncSession) -> None:
    world = await _world(db_session)
    start = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    await _create(
        db_session,
        world,
        professional=world["professional_a"],
        cabinet=world["cabinet_a"],
        start=start,
        end=start + timedelta(hours=1),
    )

    with pytest.raises(IntegrityError):
        await _create(
            db_session,
            world,
            professional=world["professional_a"],
            cabinet=world["cabinet_b"],
            start=start + timedelta(minutes=30),
            end=start + timedelta(minutes=90),
        )


@pytest.mark.asyncio
async def test_cabinet_cannot_overlap_across_professionals(db_session: AsyncSession) -> None:
    world = await _world(db_session)
    start = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
    await _create(
        db_session,
        world,
        professional=world["professional_a"],
        cabinet=world["cabinet_a"],
        start=start,
        end=start + timedelta(hours=1),
    )

    with pytest.raises(IntegrityError):
        await _create(
            db_session,
            world,
            professional=world["professional_b"],
            cabinet=world["cabinet_a"],
            start=start + timedelta(minutes=15),
            end=start + timedelta(minutes=45),
        )


@pytest.mark.asyncio
async def test_back_to_back_and_independent_ranges_remain_valid(
    db_session: AsyncSession,
) -> None:
    world = await _world(db_session)
    start = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)
    await _create(
        db_session,
        world,
        professional=world["professional_a"],
        cabinet=world["cabinet_a"],
        start=start,
        end=start + timedelta(minutes=30),
    )
    back_to_back = await _create(
        db_session,
        world,
        professional=world["professional_a"],
        cabinet=world["cabinet_a"],
        start=start + timedelta(minutes=30),
        end=start + timedelta(hours=1),
    )
    independent = await _create(
        db_session,
        world,
        professional=world["professional_b"],
        cabinet=world["cabinet_b"],
        start=start + timedelta(minutes=15),
        end=start + timedelta(minutes=45),
    )

    assert back_to_back.id != independent.id


@pytest.mark.asyncio
async def test_terminal_appointment_does_not_reserve_range(db_session: AsyncSession) -> None:
    world = await _world(db_session)
    start = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
    await _create(
        db_session,
        world,
        professional=world["professional_a"],
        cabinet=world["cabinet_a"],
        start=start,
        end=start + timedelta(hours=1),
        status="completed",
    )
    replacement = await _create(
        db_session,
        world,
        professional=world["professional_a"],
        cabinet=world["cabinet_a"],
        start=start,
        end=start + timedelta(hours=1),
    )

    assert replacement.status == "scheduled"


@pytest.mark.asyncio
@pytest.mark.parametrize("duration", [timedelta(0), timedelta(minutes=-30)])
async def test_non_positive_range_is_rejected(
    db_session: AsyncSession,
    duration: timedelta,
) -> None:
    world = await _world(db_session)
    start = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)

    with pytest.raises(IntegrityError):
        await _create(
            db_session,
            world,
            professional=world["professional_a"],
            cabinet=world["cabinet_a"],
            start=start,
            end=start + duration,
        )
