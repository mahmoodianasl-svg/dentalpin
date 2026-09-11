from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.patient_agent.dental_conversation import DentalTopic
from app.modules.patient_agent.dental_knowledge_ingestion_schemas import (
    DentalKnowledgeCorpusEntry,
    DentalKnowledgeCorpusImportRequest,
)
from app.modules.patient_agent.dental_knowledge_ingestion_service import (
    DentalKnowledgeCorpusIngestionService,
)


def _entry(**updates: object) -> DentalKnowledgeCorpusEntry:
    values: dict[str, object] = {
        "entry_key": "preventive.brushing",
        "topic": DentalTopic.PREVENTIVE_CARE,
        "locale": "en",
        "title": "Brushing basics",
        "content": "Brush twice daily with fluoride toothpaste.",
        "source_name": "Curated dental guidance",
        "source_reference": "https://example.org/preventive/brushing",
        "source_metadata": {"publisher": "example"},
    }
    values.update(updates)
    return DentalKnowledgeCorpusEntry(**values)


def _payload(*entries: DentalKnowledgeCorpusEntry) -> DentalKnowledgeCorpusImportRequest:
    return DentalKnowledgeCorpusImportRequest(
        corpus_id="governed-preventive",
        corpus_version="2026-09",
        entries=list(entries) or [_entry()],
    )


@pytest.mark.asyncio
async def test_entry_locks_are_acquired_in_stable_order_before_version_reads() -> None:
    result = SimpleNamespace(scalar_one_or_none=lambda: None)
    db = SimpleNamespace(
        execute=AsyncMock(return_value=result),
        add=lambda _: None,
        flush=AsyncMock(),
    )
    clinic_id = uuid.uuid4()
    payload = _payload(
        _entry(entry_key="preventive.flossing"),
        _entry(entry_key="preventive.brushing"),
    )

    await DentalKnowledgeCorpusIngestionService().ingest(
        db=db,
        clinic_id=clinic_id,
        actor_user_id=uuid.uuid4(),
        payload=payload,
    )

    calls = db.execute.await_args_list
    assert len(calls) == 4
    first_lock, second_lock = calls[:2]
    assert "pg_advisory_xact_lock" in str(first_lock.args[0])
    assert "pg_advisory_xact_lock" in str(second_lock.args[0])
    service = DentalKnowledgeCorpusIngestionService()
    assert first_lock.args[1]["lock_key"] == service._lock_key(
        clinic_id=clinic_id,
        entry_key="preventive.brushing",
    )
    assert second_lock.args[1]["lock_key"] == service._lock_key(
        clinic_id=clinic_id,
        entry_key="preventive.flossing",
    )


@pytest.mark.asyncio
async def test_postgres_entry_lock_blocks_competing_transaction(
    db_session: AsyncSession,
) -> None:
    bind = db_session.bind
    assert bind is not None
    factory = async_sessionmaker(bind, expire_on_commit=False)
    clinic_id = uuid.uuid4()
    entry_key = "preventive.brushing"
    service = DentalKnowledgeCorpusIngestionService()

    async with factory() as first, factory() as second:
        async with first.begin():
            await service._lock_entry_keys(
                db=first,
                clinic_id=clinic_id,
                entry_keys=[entry_key],
            )

            async def acquire_competing_lock() -> None:
                async with second.begin():
                    await service._lock_entry_keys(
                        db=second,
                        clinic_id=clinic_id,
                        entry_keys=[entry_key],
                    )

            competing = asyncio.create_task(acquire_competing_lock())
            await asyncio.sleep(0.05)
            assert not competing.done()

        await asyncio.wait_for(competing, timeout=1)


def test_lock_key_is_deterministic_and_clinic_scoped() -> None:
    service = DentalKnowledgeCorpusIngestionService()
    clinic_id = uuid.uuid4()
    entry_key = "preventive.brushing"

    first = service._lock_key(clinic_id=clinic_id, entry_key=entry_key)
    second = service._lock_key(clinic_id=clinic_id, entry_key=entry_key)

    assert first == second
    assert -(2**63) <= first < 2**63
    assert first != service._lock_key(clinic_id=uuid.uuid4(), entry_key=entry_key)


@pytest.mark.parametrize(
    "source_reference",
    [
        "http://example.org/guidance",
        "javascript:alert(1)",
        "https://user:secret@example.org/guidance",
        "https://example.org:invalid/guidance",
        "https://exam ple.org/guidance",
        "example.org/guidance",
    ],
)
def test_source_reference_requires_credential_free_https(source_reference: str) -> None:
    with pytest.raises(ValidationError, match="source_reference"):
        _entry(source_reference=source_reference)


def test_source_metadata_rejects_non_json_and_oversized_values() -> None:
    with pytest.raises(ValidationError, match="finite JSON"):
        _entry(source_metadata={"score": float("nan")})

    with pytest.raises(ValidationError, match="32768"):
        _entry(source_metadata={"notes": "x" * 33_000})
