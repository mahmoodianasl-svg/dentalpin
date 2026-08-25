"""Recall lifecycle event transaction-boundary tests."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.events import EventType, event_bus
from app.modules.recalls.service import RecallService


def _recall() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        clinic_id=uuid4(),
        patient_id=uuid4(),
        reason="hygiene",
        due_month=date(2026, 10, 1),
        priority="normal",
        status="pending",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("helper_name", "event_type", "extra_args"),
    [
        ("commit_and_publish_created", EventType.RECALL_CREATED, (True,)),
        ("commit_and_publish_snoozed", EventType.RECALL_SNOOZED, (3,)),
        ("commit_and_publish_cancelled", EventType.RECALL_CANCELLED, ()),
        ("commit_and_publish_completed", EventType.RECALL_COMPLETED, ()),
    ],
)
async def test_recall_lifecycle_event_publishes_after_commit(
    monkeypatch: pytest.MonkeyPatch,
    helper_name: str,
    event_type: str,
    extra_args: tuple,
) -> None:
    db = MagicMock()
    order: list[str] = []
    published: list[tuple[str, dict]] = []

    async def commit() -> None:
        order.append("commit")

    async def publish(published_type: str, data: dict) -> None:
        order.append("publish")
        published.append((published_type, data))

    db.commit = AsyncMock(side_effect=commit)
    monkeypatch.setattr(event_bus, "publish", publish)

    helper = getattr(RecallService, helper_name)
    await helper(db, _recall(), *extra_args)

    assert order == ["commit", "publish"]
    assert published[0][0] == event_type
    assert published[0][1]["clinic_id"]
    assert published[0][1]["recall_id"]
    if event_type == EventType.RECALL_SNOOZED:
        assert published[0][1]["snoozed_months"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("helper_name", "extra_args"),
    [
        ("commit_and_publish_created", (True,)),
        ("commit_and_publish_snoozed", (2,)),
        ("commit_and_publish_cancelled", ()),
        ("commit_and_publish_completed", ()),
    ],
)
async def test_recall_lifecycle_event_is_suppressed_when_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
    helper_name: str,
    extra_args: tuple,
) -> None:
    db = MagicMock()
    db.commit = AsyncMock(side_effect=RuntimeError("commit failed"))
    publish = AsyncMock()
    monkeypatch.setattr(event_bus, "publish", publish)

    helper = getattr(RecallService, helper_name)
    with pytest.raises(RuntimeError, match="commit failed"):
        await helper(db, _recall(), *extra_args)

    publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_guard_commits_without_created_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    db.commit = AsyncMock()
    publish = AsyncMock()
    monkeypatch.setattr(event_bus, "publish", publish)

    await RecallService.commit_and_publish_created(db, _recall(), False)

    db.commit.assert_awaited_once_with()
    publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_batch_publishes_only_after_single_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    order: list[str] = []

    async def commit() -> None:
        order.append("commit")

    async def publish(_event_type: str, _data: dict) -> None:
        order.append("publish")

    db.commit = AsyncMock(side_effect=commit)
    monkeypatch.setattr(event_bus, "publish", publish)

    await RecallService.commit_and_publish_completed_many(db, [_recall(), _recall()])

    assert order == ["commit", "publish", "publish"]
    db.commit.assert_awaited_once_with()
