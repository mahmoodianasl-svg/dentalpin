# Database migration policy

## Scope

This policy defines DentalPin's schema source of truth and recovery rules for W0.2 and later database changes.

## Schema authority

Alembic migrations are the production schema authority. SQLAlchemy metadata must describe the structural schema produced by `alembic upgrade heads`, including tables, columns and types, foreign keys, unique/check constraints, indexes and PostgreSQL index predicates.

`Base.metadata.create_all()` is a development/testing helper only. It must not be treated as the production schema definition or used to justify schema changes that are absent from Alembic history.

The authoritative model registry is `app.schema_registry.register_all_models()`. It imports every active modular `models.py` package and applies the reviewed historical migration contract so Alembic autogenerate/parity checks see the complete production-equivalent metadata surface.

## Migration requirements

Every new migration must:

1. have a unique revision and valid graph dependency;
2. upgrade cleanly from the supported predecessor state;
3. leave `alembic upgrade heads` structurally identical to the complete SQLAlchemy metadata contract;
4. provide a correct downgrade when the operation is safely reversible; or
5. be explicitly declared one-way when reverse migration would destroy, duplicate or ambiguously reconstruct production data.

CI scans migration source for `raise NotImplementedError` and requires exact agreement with the reviewed one-way revision inventory in `tests/test_alembic_roundtrip.py`. An undeclared irreversible migration, or a stale inventory entry, fails the gate.

## Current reviewed one-way revisions

- `cn_0002` — moves clinical-note attachment data into polymorphic `media_attachments` and creates additional provenance links; reversing it cannot reconstruct the legacy rows unambiguously.
- `tp_0004` — consolidates treatment media into `media.media_attachments`; reverse reconstruction is intentionally unsupported.

These entries are historical migration walls. New one-way migrations require explicit rationale in the migration docstring and review of this policy/inventory.

## Production recovery across a one-way migration

DentalPin does not perform an in-place Alembic downgrade across a reviewed one-way migration. The supported recovery strategy is:

1. create a PostgreSQL backup immediately before the deployment/migration boundary;
2. apply migrations forward;
3. prefer a forward-fix migration for defects discovered after deployment when data is valid and recoverable;
4. if database rollback is required, restore the verified pre-deployment backup instead of executing a destructive/ambiguous downgrade;
5. verify the restored database's Alembic head set and structural schema before application traffic is resumed.

W0.2 CI exercises this policy using PostgreSQL 15: it migrates a fresh database to all heads, creates a custom-format `pg_dump`, restores it into a separate database with `pg_restore --exit-on-error`, compares the source/restored Alembic head sets, and reruns structural schema parity against the restored database.

## Structural parity gate

The W0.2 schema-parity test compares a freshly migrated PostgreSQL schema with the complete SQLAlchemy metadata contract using Alembic autogenerate comparison. The gate covers structural differences such as tables, columns/types, keys, constraints, indexes and predicates.

Historical Python-side defaults and database `server_default` behavior are intentionally not conflated in that structural comparison. Runtime database defaults are owned by migrations and are exercised by migrated PostgreSQL environments; adding or changing a production server default therefore requires an Alembic migration.

## Change rule

Do not repair a parity failure by weakening the comparison, deleting a production constraint/index, or adding an ignore for unexplained drift. Determine which side reflects the shipped migration contract, correct the metadata or migration deliberately, and keep the failing case covered by CI.
