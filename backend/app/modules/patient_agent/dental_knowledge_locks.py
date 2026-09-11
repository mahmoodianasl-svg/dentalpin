from __future__ import annotations

import hashlib
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def dental_knowledge_lock_key(*, clinic_id: UUID, entry_key: str) -> int:
    digest = hashlib.sha256(f"{clinic_id}:{entry_key}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


async def lock_dental_knowledge_entries(
    *,
    db: AsyncSession,
    clinic_id: UUID,
    entry_keys: Iterable[str],
) -> None:
    """Serialize entry lifecycle changes for the current transaction.

    Sorting prevents overlapping batches from acquiring the same PostgreSQL
    transaction advisory locks in opposite order and deadlocking.
    """
    for entry_key in sorted(set(entry_keys)):
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {
                "lock_key": dental_knowledge_lock_key(
                    clinic_id=clinic_id,
                    entry_key=entry_key,
                )
            },
        )
