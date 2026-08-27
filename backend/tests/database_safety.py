"""Fail-closed safeguards for destructive database tests."""

from sqlalchemy.engine import make_url

_APPROVED_DISPOSABLE_DATABASE_NAMES = {
    "dental_schema_parity",
    "dental_schema_restore",
    "stub",
}


def assert_disposable_test_database_url(database_url: str) -> str:
    """Refuse destructive test setup unless the database is unmistakably disposable.

    The shared pytest fixture creates and drops the complete SQLAlchemy metadata, so a
    misconfigured local ``DATABASE_URL`` must fail before an engine can be created.
    Only the explicit schema-validation databases used by CI and conventional test
    database names are accepted.
    """
    try:
        database_name = make_url(database_url).database or ""
    except Exception as exc:
        raise RuntimeError(
            "Refusing destructive test setup: DATABASE_URL is not a valid isolated "
            "test database URL."
        ) from exc

    normalized = database_name.lower()
    is_disposable = (
        normalized in _APPROVED_DISPOSABLE_DATABASE_NAMES
        or normalized.endswith("_test")
        or normalized.startswith("test_")
        or "_test_" in normalized
    )
    if not is_disposable:
        raise RuntimeError(
            "Refusing destructive test setup against non-disposable database "
            f"{database_name!r}. Use an isolated test database name."
        )

    return database_url
