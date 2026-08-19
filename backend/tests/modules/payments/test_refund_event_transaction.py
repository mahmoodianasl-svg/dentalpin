"""Refund event transaction-boundary tests."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.events import EventType, event_bus
from app.modules.payments.workflow import refund_payment


def _db_with_no_existing_refunds() -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    total = MagicMock()
    total.scalar_one.return_value = Decimal("0")
    db.execute.side_effect = [MagicMock(), total]
    return db


@pytest.mark.asyncio
async def test_refund_commits_before_event_publication(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db_with_no_existing_refunds()
    order: list[str] = []
    published: list[tuple[str, dict]] = []

    async def commit() -> None:
        order.append("commit")

    async def publish(event_type: str, data: dict) -> None:
        order.append("publish")
        published.append((event_type, data))

    db.commit.side_effect = commit
    monkeypatch.setattr(event_bus, "publish", publish)

    actor_id = uuid4()
    await refund_payment(
        db,
        clinic_id=uuid4(),
        payment=SimpleNamespace(id=uuid4(), amount=Decimal("100.00")),
        amount=Decimal("25.00"),
        method="cash",
        reason_code="overpaid",
        reason_note=None,
        refunded_by=actor_id,
    )

    assert order == ["commit", "publish"]
    assert published[0][0] == EventType.PAYMENT_REFUNDED
    assert published[0][1]["refunded_by"] == str(actor_id)


@pytest.mark.asyncio
async def test_refund_does_not_publish_when_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db_with_no_existing_refunds()
    db.commit.side_effect = RuntimeError("commit failed")
    publish = AsyncMock()
    monkeypatch.setattr(event_bus, "publish", publish)

    with pytest.raises(RuntimeError, match="commit failed"):
        await refund_payment(
            db,
            clinic_id=uuid4(),
            payment=SimpleNamespace(id=uuid4(), amount=Decimal("100.00")),
            amount=Decimal("25.00"),
            method="cash",
            reason_code="overpaid",
            reason_note=None,
            refunded_by=uuid4(),
        )

    publish.assert_not_awaited()
