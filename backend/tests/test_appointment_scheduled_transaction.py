"""Appointment-scheduled event transaction-boundary tests."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.events import EventType, event_bus
from app.modules.agenda.service import AppointmentService
from app.modules.migration_import.mappers.base import MapperContext


def _appointment() -> SimpleNamespace:
    start = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(),
        clinic_id=uuid4(),
        patient_id=uuid4(),
        professional_id=uuid4(),
        start_time=start,
        end_time=start + timedelta(minutes=30),
        treatment_type="Check-up",
        cabinet="Room 1",
    )


@pytest.mark.asyncio
async def test_scheduled_event_publishes_after_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    db = MagicMock()
    db.commit = AsyncMock()
    order: list[str] = []
    published: list[tuple[str, dict]] = []

    async def commit() -> None:
        order.append("commit")

    async def publish(event_type: str, data: dict) -> None:
        order.append("publish")
        published.append((event_type, data))

    db.commit.side_effect = commit
    monkeypatch.setattr(event_bus, "publish", publish)

    appointment = _appointment()
    await AppointmentService.commit_and_publish_scheduled(db, appointment)

    assert order == ["commit", "publish"]
    assert published[0][0] == EventType.APPOINTMENT_SCHEDULED
    assert published[0][1]["appointment_id"] == str(appointment.id)


@pytest.mark.asyncio
async def test_scheduled_event_is_suppressed_when_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    db.commit = AsyncMock(side_effect=RuntimeError("commit failed"))
    publish = AsyncMock()
    monkeypatch.setattr(event_bus, "publish", publish)

    with pytest.raises(RuntimeError, match="commit failed"):
        await AppointmentService.commit_and_publish_scheduled(db, _appointment())

    publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_context_discards_savepoint_events_and_publishes_committed_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publish = AsyncMock()
    monkeypatch.setattr(event_bus, "publish", publish)
    ctx = MapperContext(
        db=MagicMock(),
        clinic_id=uuid4(),
        job_id=uuid4(),
        resolver=MagicMock(),
        import_fiscal_compliance=False,
        created_by=uuid4(),
    )

    ctx.queue_event("kept", {"id": "1"})
    checkpoint = ctx.pending_event_checkpoint()
    ctx.queue_event("rolled-back", {"id": "2"})
    ctx.discard_events_after(checkpoint)

    await ctx.publish_committed_events()

    publish.assert_awaited_once_with("kept", {"id": "1"})
    assert ctx.pending_events == []
