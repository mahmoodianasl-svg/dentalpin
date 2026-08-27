"""Budget lifecycle event transaction-boundary tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.events import (
    EventType,
    commit_and_publish_queued_events,
    event_bus,
    queued_after_commit,
)
from app.modules.budget.service import BudgetHistoryService
from app.modules.budget.workflow import BudgetWorkflowService


def _budget(*, status: str = "draft") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        clinic_id=uuid4(),
        patient_id=uuid4(),
        created_by=uuid4(),
        budget_number="B-2026-001",
        total=1250,
        status=status,
        items=[SimpleNamespace(id=uuid4())],
        version=1,
        viewed_at=None,
        last_reminder_sent_at=None,
    )


def _db() -> MagicMock:
    db = MagicMock()
    db.info = {}
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_send_budget_publishes_only_after_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db()
    budget = _budget()
    order: list[str] = []
    published: list[tuple[str, dict]] = []

    monkeypatch.setattr(BudgetHistoryService, "add_entry", AsyncMock())

    async def commit() -> None:
        order.append("commit")

    async def publish(event_type: str, data: dict) -> None:
        order.append("publish")
        published.append((event_type, data))

    db.commit = AsyncMock(side_effect=commit)
    monkeypatch.setattr(event_bus, "publish", publish)

    await BudgetWorkflowService.send_budget(db, budget, uuid4(), send_method="manual")

    assert order == []
    assert queued_after_commit(db)[0][0] == EventType.BUDGET_SENT

    await commit_and_publish_queued_events(db)

    assert order == ["commit", "publish"]
    assert published[0][0] == EventType.BUDGET_SENT
    assert published[0][1]["budget_id"] == str(budget.id)


@pytest.mark.asyncio
async def test_failed_commit_suppresses_queued_budget_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db()
    budget = _budget()
    monkeypatch.setattr(BudgetHistoryService, "add_entry", AsyncMock())
    publish = AsyncMock()
    monkeypatch.setattr(event_bus, "publish", publish)

    await BudgetWorkflowService.send_budget(db, budget, uuid4())
    db.commit = AsyncMock(side_effect=RuntimeError("commit failed"))

    with pytest.raises(RuntimeError, match="commit failed"):
        await commit_and_publish_queued_events(db)

    publish.assert_not_awaited()
    assert queued_after_commit(db) == []


@pytest.mark.asyncio
async def test_cancel_budget_keeps_no_echo_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db()
    budget = _budget(status="sent")
    monkeypatch.setattr(BudgetHistoryService, "add_entry", AsyncMock())
    lookup_plan = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(BudgetWorkflowService, "_lookup_plan_id", lookup_plan)

    await BudgetWorkflowService.cancel_budget(
        db,
        budget,
        cancelled_by=uuid4(),
        publish_event=False,
    )

    assert budget.status == "cancelled"
    assert queued_after_commit(db) == []
    lookup_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_budget_queues_event_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db()
    budget = _budget(status="sent")
    plan_id = uuid4()
    monkeypatch.setattr(BudgetHistoryService, "add_entry", AsyncMock())
    monkeypatch.setattr(BudgetWorkflowService, "_lookup_plan_id", AsyncMock(return_value=plan_id))

    await BudgetWorkflowService.cancel_budget(db, budget, cancelled_by=uuid4())

    queued = queued_after_commit(db)
    assert len(queued) == 1
    assert queued[0][0] == EventType.BUDGET_CANCELLED
    assert queued[0][1]["plan_id"] == str(plan_id)
