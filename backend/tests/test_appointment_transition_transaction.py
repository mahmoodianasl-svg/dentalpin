"""Appointment-transition event transaction-boundary tests."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.events import EventType, event_bus
from app.modules.agenda.service import TRANSITION_EVENT_TYPES, AppointmentService


def _appointment(*, status: str = "checked_in") -> SimpleNamespace:
    changed_at = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(),
        clinic_id=uuid4(),
        patient_id=uuid4(),
        professional_id=uuid4(),
        treatment_type="Check-up",
        cabinet="Room 1",
        cabinet_id=uuid4(),
        start_time=changed_at + timedelta(hours=1),
        end_time=changed_at + timedelta(hours=1, minutes=30),
        status=status,
        current_status_since=changed_at,
    )


@pytest.mark.asyncio
async def test_transition_is_persistence_only(monkeypatch: pytest.MonkeyPatch) -> None:
    db = MagicMock()
    db.flush = AsyncMock()
    publish = AsyncMock()
    monkeypatch.setattr(event_bus, "publish", publish)
    appointment = _appointment(status="scheduled")

    await AppointmentService.transition(db, appointment, "checked_in")

    assert appointment.status == "checked_in"
    db.flush.assert_awaited_once()
    publish.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("to_status", list(TRANSITION_EVENT_TYPES))
async def test_transition_events_publish_after_commit(
    monkeypatch: pytest.MonkeyPatch,
    to_status: str,
) -> None:
    db = MagicMock()
    db.commit = AsyncMock()
    order: list[str] = []
    published: list[tuple[str, dict]] = []

    async def commit() -> None:
        order.append("commit")

    async def publish(event_type: str, data: dict) -> None:
        order.append(event_type)
        published.append((event_type, data))

    db.commit.side_effect = commit
    monkeypatch.setattr(event_bus, "publish", publish)
    appointment = _appointment(status=to_status)
    changed_by = uuid4()

    await AppointmentService.commit_and_publish_transition(
        db,
        appointment,
        from_status="scheduled",
        changed_by=changed_by,
        note="front desk",
    )

    assert order == [
        "commit",
        EventType.APPOINTMENT_STATUS_CHANGED,
        TRANSITION_EVENT_TYPES[to_status],
    ]
    assert published[0][1] == published[1][1]
    assert published[0][1] == {
        "appointment_id": str(appointment.id),
        "clinic_id": str(appointment.clinic_id),
        "patient_id": str(appointment.patient_id),
        "professional_id": str(appointment.professional_id),
        "treatment_type": appointment.treatment_type,
        "cabinet": appointment.cabinet,
        "start_time": appointment.start_time.isoformat(),
        "end_time": appointment.end_time.isoformat(),
        "from_status": "scheduled",
        "to_status": to_status,
        "changed_at": appointment.current_status_since.isoformat(),
        "changed_by": str(changed_by),
        "note": "front desk",
    }


@pytest.mark.asyncio
async def test_transition_events_are_suppressed_when_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    db.commit = AsyncMock(side_effect=RuntimeError("commit failed"))
    publish = AsyncMock()
    monkeypatch.setattr(event_bus, "publish", publish)

    with pytest.raises(RuntimeError, match="commit failed"):
        await AppointmentService.commit_and_publish_transition(
            db,
            _appointment(status="cancelled"),
            from_status="scheduled",
        )

    publish.assert_not_awaited()
