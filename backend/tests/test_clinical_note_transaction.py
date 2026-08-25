"""Clinical-note event transaction-boundary tests."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.events import EventType, event_bus
from app.modules.clinical_notes.models import (
    NOTE_TYPE_ADMINISTRATIVE,
    NOTE_TYPE_APPOINTMENT_ADMINISTRATIVE,
    NOTE_TYPE_APPOINTMENT_CLINICAL,
    NOTE_TYPE_DIAGNOSIS,
    NOTE_TYPE_TREATMENT,
    NOTE_TYPE_TREATMENT_PLAN,
)
from app.modules.clinical_notes.service import NoteService


def _note(note_type: str = NOTE_TYPE_DIAGNOSIS) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        clinic_id=uuid4(),
        note_type=note_type,
        owner_type="patient",
        owner_id=uuid4(),
        tooth_number=11 if note_type == NOTE_TYPE_DIAGNOSIS else None,
        author_id=uuid4(),
        body="<p>Clinical   observation</p>",
        created_at=datetime(2026, 8, 25, 14, 0, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("note_type", "event_type"),
    [
        (NOTE_TYPE_ADMINISTRATIVE, EventType.CLINICAL_NOTE_ADMINISTRATIVE_CREATED),
        (NOTE_TYPE_DIAGNOSIS, EventType.CLINICAL_NOTE_DIAGNOSIS_CREATED),
        (NOTE_TYPE_TREATMENT, EventType.CLINICAL_NOTE_TREATMENT_CREATED),
        (NOTE_TYPE_TREATMENT_PLAN, EventType.CLINICAL_NOTE_PLAN_CREATED),
        (
            NOTE_TYPE_APPOINTMENT_CLINICAL,
            EventType.CLINICAL_NOTE_APPOINTMENT_CLINICAL_CREATED,
        ),
        (
            NOTE_TYPE_APPOINTMENT_ADMINISTRATIVE,
            EventType.CLINICAL_NOTE_APPOINTMENT_ADMINISTRATIVE_CREATED,
        ),
    ],
)
def test_created_event_uses_canonical_type_and_payload(
    note_type: str,
    event_type: str,
) -> None:
    note = _note(note_type)
    patient_id = uuid4()

    actual_type, payload = NoteService.created_event(note, patient_id)

    assert actual_type == event_type
    assert payload == {
        "clinic_id": str(note.clinic_id),
        "patient_id": str(patient_id),
        "note_id": str(note.id),
        "note_type": note_type,
        "owner_type": note.owner_type,
        "owner_id": str(note.owner_id),
        "tooth_number": note.tooth_number,
        "user_id": str(note.author_id),
        "body_excerpt": "Clinical observation",
        "occurred_at": note.created_at.isoformat(),
    }


@pytest.mark.asyncio
async def test_created_event_publishes_after_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    db = MagicMock()
    order: list[str] = []
    published: list[tuple[str, dict]] = []

    async def commit() -> None:
        order.append("commit")

    async def publish(event_type: str, payload: dict) -> None:
        order.append("publish")
        published.append((event_type, payload))

    db.commit = AsyncMock(side_effect=commit)
    monkeypatch.setattr(event_bus, "publish", publish)

    note = _note()
    patient_id = uuid4()
    await NoteService.commit_and_publish_created(db, note, patient_id)

    assert order == ["commit", "publish"]
    assert published[0][0] == EventType.CLINICAL_NOTE_DIAGNOSIS_CREATED
    assert published[0][1]["patient_id"] == str(patient_id)


@pytest.mark.asyncio
async def test_created_event_is_suppressed_when_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    db.commit = AsyncMock(side_effect=RuntimeError("commit failed"))
    publish = AsyncMock()
    monkeypatch.setattr(event_bus, "publish", publish)

    with pytest.raises(RuntimeError, match="commit failed"):
        await NoteService.commit_and_publish_created(db, _note(), uuid4())

    publish.assert_not_awaited()
