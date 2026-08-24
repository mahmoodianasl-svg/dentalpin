"""Patient lifecycle event transaction-boundary tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.events import EventType, event_bus
from app.modules.migration_import.mappers.base import MapperContext
from app.modules.migration_import.mappers.patient import PatientMapper
from app.modules.patients.service import PatientService


def _patient() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), clinic_id=uuid4())


def _mapper_context(*, resolver_set_error: Exception | None = None) -> MapperContext:
    resolver = MagicMock()
    resolver.get = AsyncMock(return_value=None)
    resolver.set = AsyncMock(side_effect=resolver_set_error)
    return MapperContext(
        db=MagicMock(),
        clinic_id=uuid4(),
        job_id=uuid4(),
        resolver=resolver,
        import_fiscal_compliance=False,
        created_by=uuid4(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("helper_name", "event_type", "extra_args"),
    [
        ("commit_and_publish_created", EventType.PATIENT_CREATED, ()),
        ("commit_and_publish_updated", EventType.PATIENT_UPDATED, (["email"],)),
        ("commit_and_publish_archived", EventType.PATIENT_ARCHIVED, ()),
    ],
)
async def test_patient_lifecycle_event_publishes_after_commit(
    monkeypatch: pytest.MonkeyPatch,
    helper_name: str,
    event_type: str,
    extra_args: tuple,
) -> None:
    db = MagicMock()
    db.commit = AsyncMock()
    order: list[str] = []
    published: list[tuple[str, dict]] = []

    async def commit() -> None:
        order.append("commit")

    async def publish(published_type: str, data: dict) -> None:
        order.append("publish")
        published.append((published_type, data))

    db.commit.side_effect = commit
    monkeypatch.setattr(event_bus, "publish", publish)

    patient = _patient()
    helper = getattr(PatientService, helper_name)
    await helper(db, patient, *extra_args)

    assert order == ["commit", "publish"]
    assert published[0][0] == event_type
    assert published[0][1]["patient_id"] == str(patient.id)
    assert published[0][1]["clinic_id"] == str(patient.clinic_id)
    if event_type == EventType.PATIENT_UPDATED:
        assert published[0][1]["changes"] == ["email"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("helper_name", "extra_args"),
    [
        ("commit_and_publish_created", ()),
        ("commit_and_publish_updated", (["phone"],)),
        ("commit_and_publish_archived", ()),
    ],
)
async def test_patient_lifecycle_event_is_suppressed_when_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
    helper_name: str,
    extra_args: tuple,
) -> None:
    db = MagicMock()
    db.commit = AsyncMock(side_effect=RuntimeError("commit failed"))
    publish = AsyncMock()
    monkeypatch.setattr(event_bus, "publish", publish)

    helper = getattr(PatientService, helper_name)
    with pytest.raises(RuntimeError, match="commit failed"):
        await helper(db, _patient(), *extra_args)

    publish.assert_not_awaited()


def test_patient_lifecycle_payload_builders_share_canonical_identity() -> None:
    patient = _patient()

    assert PatientService.created_event_payload(patient) == {
        "patient_id": str(patient.id),
        "clinic_id": str(patient.clinic_id),
    }
    assert PatientService.updated_event_payload(patient, ["email", "phone"]) == {
        "patient_id": str(patient.id),
        "clinic_id": str(patient.clinic_id),
        "changes": ["email", "phone"],
    }
    assert PatientService.archived_event_payload(patient) == {
        "patient_id": str(patient.id),
        "clinic_id": str(patient.clinic_id),
    }


@pytest.mark.asyncio
async def test_patient_mapper_queues_created_event_after_entity_is_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _mapper_context()
    patient = SimpleNamespace(id=uuid4(), clinic_id=ctx.clinic_id)
    monkeypatch.setattr(
        PatientService,
        "create_patient",
        AsyncMock(return_value=patient),
    )

    result = await PatientMapper().apply(
        ctx,
        entity_type="patient",
        payload={"given_name": "Ada", "family_name": "Lovelace"},
        raw={},
        canonical_uuid=str(uuid4()),
        source_id="42",
        source_system="test",
    )

    assert result == patient.id
    assert ctx.pending_events == [
        (EventType.PATIENT_CREATED, PatientService.created_event_payload(patient))
    ]


@pytest.mark.asyncio
async def test_patient_mapper_does_not_queue_event_when_mapping_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _mapper_context(resolver_set_error=RuntimeError("mapping failed"))
    patient = SimpleNamespace(id=uuid4(), clinic_id=ctx.clinic_id)
    monkeypatch.setattr(
        PatientService,
        "create_patient",
        AsyncMock(return_value=patient),
    )

    with pytest.raises(RuntimeError, match="mapping failed"):
        await PatientMapper().apply(
            ctx,
            entity_type="patient",
            payload={"given_name": "Ada", "family_name": "Lovelace"},
            raw={},
            canonical_uuid=str(uuid4()),
            source_id="42",
            source_system="test",
        )

    assert ctx.pending_events == []
