"""Session-scoped event queue for commit-before-publish boundaries.

This is an in-memory request/handler queue, not a durable outbox. It lets a
service nested inside a larger transaction describe its domain events without
committing the caller's work or exposing uncommitted rows to subscribers.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .bus import event_bus

QueuedEvent = tuple[str, dict[str, Any]]

_QUEUED_EVENTS_KEY = "event_bus.after_commit"


def queue_after_commit(
    db: AsyncSession,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Queue one event on ``db`` for its outer transaction owner."""
    pending: list[QueuedEvent] = db.info.setdefault(_QUEUED_EVENTS_KEY, [])
    pending.append((event_type, data))


def queued_after_commit(db: AsyncSession) -> list[QueuedEvent]:
    """Return a snapshot of events currently waiting on ``db``."""
    return list(db.info.get(_QUEUED_EVENTS_KEY, []))


def discard_queued_events(db: AsyncSession) -> None:
    """Discard events whose containing transaction will not commit."""
    db.info.pop(_QUEUED_EVENTS_KEY, None)


async def commit_and_publish_queued_events(db: AsyncSession) -> None:
    """Commit ``db`` once, then publish its queued events in FIFO order.

    The queue is detached before the commit attempt. A failed commit therefore
    cannot leak stale events into a later transaction if the session is reused.
    """
    pending = list(db.info.pop(_QUEUED_EVENTS_KEY, []))
    await db.commit()
    for event_type, data in pending:
        await event_bus.publish(event_type, data)
