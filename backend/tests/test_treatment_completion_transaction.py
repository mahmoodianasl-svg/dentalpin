"""Treatment-completion event transaction-boundary tests."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.events import (
    EventType,
    commit_and_publish_queued_events,
    event_bus,
    queue_after_commit,
    queued_after_commit,
)
from app.modules.odontogram.service import TreatmentService
from app.modules.treatment_plan.service import TreatmentPlanService


def _db(*, commit_error: Exception | None = None) -> MagicMock:
    db = MagicMock()
    db.info = {}
    db.commit = AsyncMock(side_effect=commit_error)
    db.flush = AsyncMock()
    return db


def _treatment() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        patient_id=uuid4(),
        status="planned",
        performed_at=None,
        performed_by=None,
        notes=None,
        clinical_type="filling",
        catalog_item=None,
        catalog_item_id=None,
        teeth=[SimpleNamespace(tooth_number=11), SimpleNamespace(tooth_number=12)],
        budget_item_id=None,
        price_snapshot=Decimal("125.50"),
    )


@pytest.mark.asyncio
async def test_queued_events_publish_after_one_commit_in_fifo_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db()
    order: list[str] = []
    published: list[tuple[str, dict]] = []

    async def commit() -> None:
        order.append("commit")

    async def publish(event_type: str, payload: dict) -> None:
        order.append(event_type)
        published.append((event_type, payload))

    db.commit.side_effect = commit
    monkeypatch.setattr(event_bus, "publish", publish)
    queue_after_commit(db, "first", {"sequence": 1})
    queue_after_commit(db, "second", {"sequence": 2})

    await commit_and_publish_queued_events(db)

    assert order == ["commit", "first", "second"]
    assert published == [("first", {"sequence": 1}), ("second", {"sequence": 2})]
    assert queued_after_commit(db) == []


@pytest.mark.asyncio
async def test_failed_commit_discards_queued_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(commit_error=RuntimeError("commit failed"))
    publish = AsyncMock()
    monkeypatch.setattr(event_bus, "publish", publish)
    queue_after_commit(db, "must-not-publish", {"id": "1"})

    with pytest.raises(RuntimeError, match="commit failed"):
        await commit_and_publish_queued_events(db)

    publish.assert_not_awaited()
    assert queued_after_commit(db) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("publish_price", "unit_price"), [(True, "251.00"), (False, None)])
async def test_treatment_performed_is_queued_with_canonical_price_contract(
    monkeypatch: pytest.MonkeyPatch,
    publish_price: bool,
    unit_price: str | None,
) -> None:
    db = _db()
    treatment = _treatment()
    publish = AsyncMock()
    monkeypatch.setattr(event_bus, "publish", publish)
    monkeypatch.setattr(
        TreatmentService,
        "get_treatment",
        AsyncMock(return_value=treatment),
    )

    actual = await TreatmentService.perform(
        db,
        clinic_id=uuid4(),
        treatment_id=treatment.id,
        user_id=uuid4(),
        publish_price=publish_price,
    )

    assert actual is treatment
    publish.assert_not_awaited()
    [(event_type, payload)] = queued_after_commit(db)
    assert event_type == EventType.ODONTOGRAM_TREATMENT_PERFORMED
    assert payload["treatment_id"] == str(treatment.id)
    assert payload["tooth_numbers"] == [11, 12]
    assert payload["unit_price"] == unit_price


@pytest.mark.asyncio
async def test_session_completion_queues_event_without_precommit_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db()
    session = SimpleNamespace(
        id=uuid4(),
        sequence=1,
        label="Preparation",
        amount=Decimal("200.00"),
        status="pending",
        completed_at=None,
        completed_by=None,
        notes=None,
    )
    pending_session = SimpleNamespace(status="pending")
    item = SimpleNamespace(
        id=uuid4(),
        treatment_id=uuid4(),
        treatment=SimpleNamespace(patient_id=uuid4()),
        sessions=[session, pending_session],
        status="pending",
    )
    publish = AsyncMock()
    monkeypatch.setattr(event_bus, "publish", publish)
    monkeypatch.setattr(
        TreatmentPlanService,
        "_load_item_with_sessions",
        AsyncMock(return_value=item),
    )

    actual = await TreatmentPlanService.complete_session(
        db,
        clinic_id=uuid4(),
        plan_id=uuid4(),
        item_id=item.id,
        session_id=session.id,
        user_id=uuid4(),
    )

    assert actual is item
    assert session.status == "completed"
    publish.assert_not_awaited()
    [(event_type, payload)] = queued_after_commit(db)
    assert event_type == EventType.TREATMENT_PLAN_ITEM_SESSION_COMPLETED
    assert payload["session_id"] == str(session.id)
    assert payload["amount"] == "200.00"


@pytest.mark.asyncio
async def test_final_session_queues_the_full_completion_fanout_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db()
    session = SimpleNamespace(
        id=uuid4(),
        sequence=1,
        label="Placement",
        amount=Decimal("600.00"),
        status="pending",
        completed_at=None,
        completed_by=None,
        notes=None,
    )
    treatment = SimpleNamespace(patient_id=uuid4(), catalog_item=None)
    item = SimpleNamespace(
        id=uuid4(),
        treatment_id=uuid4(),
        treatment=treatment,
        sessions=[session],
        status="pending",
        completed_at=None,
        completed_by=None,
        completed_without_appointment=False,
        notes=None,
    )
    publish = AsyncMock()
    monkeypatch.setattr(event_bus, "publish", publish)
    monkeypatch.setattr(
        TreatmentPlanService,
        "_load_item_with_sessions",
        AsyncMock(return_value=item),
    )

    async def perform(**kwargs) -> SimpleNamespace:
        queue_after_commit(
            kwargs["db"],
            EventType.ODONTOGRAM_TREATMENT_PERFORMED,
            {"treatment_id": str(item.treatment_id)},
        )
        return treatment

    async def complete_plan(
        queued_db: MagicMock,
        clinic_id,
        plan_id,
    ) -> None:
        queue_after_commit(
            queued_db,
            "treatment_plan.status_changed",
            {"clinic_id": str(clinic_id), "plan_id": str(plan_id)},
        )

    monkeypatch.setattr(TreatmentService, "perform", perform)
    monkeypatch.setattr(TreatmentPlanService, "_check_and_complete_plan", complete_plan)

    await TreatmentPlanService.complete_session(
        db,
        clinic_id=uuid4(),
        plan_id=uuid4(),
        item_id=item.id,
        session_id=session.id,
        user_id=uuid4(),
    )

    publish.assert_not_awaited()
    assert [event_type for event_type, _ in queued_after_commit(db)] == [
        EventType.TREATMENT_PLAN_ITEM_SESSION_COMPLETED,
        EventType.ODONTOGRAM_TREATMENT_PERFORMED,
        "treatment_plan.treatment_completed",
        EventType.TREATMENT_PLAN_ITEM_COMPLETED_WITHOUT_NOTE,
        "treatment_plan.status_changed",
    ]
