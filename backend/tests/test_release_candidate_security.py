"""Focused security regressions for final release-candidate qualification."""

import json
from unittest.mock import AsyncMock

import pytest

from app.main import _validated_allowed_origins, readiness_check
from app.version import VERSION
from tests.database_safety import assert_disposable_test_database_url


def test_destructive_db_guard_accepts_ci_test_database() -> None:
    url = "postgresql+asyncpg://dental:testpass@localhost:5432/dental_clinic_test"
    assert assert_disposable_test_database_url(url) == url


@pytest.mark.parametrize(
    "database_name",
    ["dental_schema_parity", "dental_schema_restore", "stub"],
)
def test_destructive_db_guard_accepts_approved_ci_databases(database_name: str) -> None:
    url = f"postgresql+asyncpg://dental:testpass@localhost:5432/{database_name}"
    assert assert_disposable_test_database_url(url) == url


@pytest.mark.parametrize("database_name", ["dental_clinic", "postgres", "production"])
def test_destructive_db_guard_rejects_non_disposable_database(database_name: str) -> None:
    url = f"postgresql+asyncpg://dental:supersecret@prod-db:5432/{database_name}"
    with pytest.raises(RuntimeError) as exc_info:
        assert_disposable_test_database_url(url)

    assert database_name in str(exc_info.value)
    assert "supersecret" not in str(exc_info.value)
    assert "prod-db" not in str(exc_info.value)


def test_production_cors_rejects_credentialed_wildcard() -> None:
    with pytest.raises(RuntimeError, match="ALLOWED_ORIGINS"):
        _validated_allowed_origins("production", ["*"])


def test_production_cors_accepts_explicit_origin() -> None:
    origin = "https://clinic.example"
    assert _validated_allowed_origins("production", [origin]) == [origin]


def test_development_cors_adds_local_origins_without_duplicates() -> None:
    origins = _validated_allowed_origins("development", ["http://localhost:3000"])
    assert origins.count("http://localhost:3000") == 1
    assert "http://127.0.0.1:3000" in origins


@pytest.mark.asyncio
async def test_readiness_failure_does_not_expose_database_error() -> None:
    db = AsyncMock()
    db.execute.side_effect = RuntimeError("password=supersecret host=prod-db.internal")

    response = await readiness_check(db)
    body = json.loads(response.body)

    assert response.status_code == 503
    assert body == {"status": "unready", "version": VERSION}
    assert b"supersecret" not in response.body
    assert b"prod-db.internal" not in response.body
