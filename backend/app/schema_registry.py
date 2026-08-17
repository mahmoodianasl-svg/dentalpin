"""Authoritative SQLAlchemy model registration and migration metadata contract.

Alembic autogenerate and schema-parity validation only see tables whose model
modules have been imported into ``Base.metadata``. DentalPin is modular, so a
hand-written list in ``alembic/env.py`` previously left active tables out of
the metadata contract.

W0.2 treats the shipped Alembic history as the schema source of truth. Some
legacy ORM declarations also contain ``index=True`` shortcuts that were never
created by migrations, while a few migration-owned partial indexes and checks
were never represented in the ORM metadata.

The migration contract is applied to a cloned ``MetaData`` object rather than
to global ``Base.metadata``. This is deliberate: application/unit-test helpers
may still use the ORM metadata, while Alembic and the parity gate consume an
isolated production-equivalent metadata view with no process-global side
effects.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint, text
from sqlalchemy.schema import MetaData, Table

from app.database import Base

CORE_MODEL_MODULES: tuple[str, ...] = (
    "app.core.agents.models",
    "app.core.auth.models",
    "app.core.plugins.db_models",
)

MODULES_ROOT = Path(__file__).resolve().parent / "modules"

# ORM-generated indexes that are absent from the authoritative migration
# history. They are removed only from the cloned migration metadata; ordinary
# Base.metadata remains untouched for application/test helper compatibility.
MODEL_ONLY_INDEXES: tuple[str, ...] = (
    "ix_budget_access_logs_budget_id",
    "ix_budgets_public_token",
    "ix_catalog_item_sessions_catalog_item_id",
    "ix_invoice_payments_clinic_id",
    "ix_invoice_payments_invoice_id",
    "ix_invoice_payments_payment_id",
    "ix_patient_earned_entries_clinic_id",
    "ix_patient_earned_entries_patient_id",
    "ix_payment_allocations_budget_id",
    "ix_payment_allocations_clinic_id",
    "ix_payment_allocations_payment_id",
    "ix_payment_history_clinic_id",
    "ix_payment_history_payment_id",
    "ix_payments_clinic_id",
    "ix_payments_patient_id",
    "ix_planned_treatment_item_sessions_plan_item_id",
    "ix_refunds_clinic_id",
    "ix_refunds_payment_id",
    "ix_verifactu_settings_clinic_id",
)


def discover_module_model_modules() -> tuple[str, ...]:
    """Return every active module package that defines ``models.py``."""
    return tuple(
        f"app.modules.{entry.name}.models"
        for entry in sorted(MODULES_ROOT.iterdir(), key=lambda path: path.name)
        if entry.is_dir() and (entry / "models.py").is_file()
    )


def _remove_index(metadata: MetaData, name: str) -> None:
    for table in metadata.tables.values():
        for index in tuple(table.indexes):
            if index.name == name:
                table.indexes.remove(index)


def _has_index(table: Table, name: str) -> bool:
    return any(index.name == name for index in table.indexes)


def _has_constraint(table: Table, name: str) -> bool:
    return any(constraint.name == name for constraint in table.constraints)


def _add_index(table: Table, name: str, *expressions: object, **kwargs: object) -> None:
    if not _has_index(table, name):
        Index(name, *expressions, **kwargs)


def _add_check(table: Table, name: str, sqltext: str) -> None:
    if not _has_constraint(table, name):
        table.append_constraint(CheckConstraint(sqltext, name=name))


def apply_migration_contract(metadata: MetaData) -> None:
    """Make a metadata copy describe the schema produced by migrations."""
    for index_name in MODEL_ONLY_INDEXES:
        _remove_index(metadata, index_name)

    # budget migrations own this public-token unique index name.
    budgets = metadata.tables["budgets"]
    _add_index(budgets, "idx_budgets_public_token", budgets.c.public_token, unique=True)

    # Recall/outreach indexes introduced by pat_0003.
    patients = metadata.tables["patients"]
    _add_index(
        patients,
        "ix_patients_clinic_status",
        patients.c.clinic_id,
        patients.c.status,
    )
    _add_index(
        patients,
        "ix_patients_clinic_do_not_contact_active",
        patients.c.clinic_id,
        postgresql_where=text("do_not_contact = false"),
    )

    # Billing's imputation amount must remain positive (bil_0004).
    invoice_payments = metadata.tables["invoice_payments"]
    _add_check(invoice_payments, "ck_invpay_amount_positive", "amount > 0")

    # migration_import closed-list state/severity constraints (mig_0001).
    _add_check(
        metadata.tables["migration_import_jobs"],
        "ck_migration_import_job_status",
        "status IN ('uploaded','validating','validated','previewing','executing','completed','failed')",
    )
    _add_check(
        metadata.tables["migration_import_file_stagings"],
        "ck_migration_file_staging_status",
        "status IN ('pending','received','missing')",
    )
    _add_check(
        metadata.tables["migration_import_warnings"],
        "ck_migration_import_warning_severity",
        "severity IN ('info','warn','error')",
    )

    # Periodontogram partial indexes from perio_0001.
    perio = metadata.tables["periodontogram_snapshots"]
    _add_index(
        perio,
        "ix_perio_snap_patient_closed_at",
        perio.c.patient_id,
        perio.c.closed_at.desc(),
        postgresql_where=text("status = 'closed'"),
    )
    _add_index(
        perio,
        "uq_perio_snap_one_draft_per_patient",
        perio.c.patient_id,
        unique=True,
        postgresql_where=text("status = 'draft'"),
    )

    # Verifactu vfy_0001/vfy_0002 schema artifacts.
    vfy_settings = metadata.tables["verifactu_settings"]
    if not _has_constraint(vfy_settings, "uq_verifactu_settings_clinic"):
        vfy_settings.append_constraint(
            UniqueConstraint(vfy_settings.c.clinic_id, name="uq_verifactu_settings_clinic")
        )
    _add_index(vfy_settings, "ix_verifactu_settings_clinic_id", vfy_settings.c.clinic_id)
    _add_check(
        vfy_settings,
        "ck_verifactu_settings_environment",
        "environment IN ('test','prod')",
    )
    if not _has_constraint(vfy_settings, "fk_verifactu_settings_declaracion_signer"):
        vfy_settings.append_constraint(
            ForeignKeyConstraint(
                [vfy_settings.c.declaracion_responsable_signed_by],
                [metadata.tables["users"].c.id],
                name="fk_verifactu_settings_declaracion_signer",
                ondelete="SET NULL",
            )
        )

    vfy_certificates = metadata.tables["verifactu_certificates"]
    _add_index(
        vfy_certificates,
        "ux_verifactu_certificates_one_active_per_clinic",
        vfy_certificates.c.clinic_id,
        unique=True,
        postgresql_where=text("is_active = true"),
    )

    vfy_records = metadata.tables["verifactu_records"]
    _add_check(
        vfy_records,
        "ck_verifactu_record_type",
        "record_type IN ('alta','anulacion')",
    )
    _add_check(
        vfy_records,
        "ck_verifactu_record_tipo_factura",
        "tipo_factura IN ('F1','F2','F3','R1','R2','R3','R4','R5')",
    )
    _add_check(
        vfy_records,
        "ck_verifactu_record_state",
        "state IN ('pending','sending','accepted','accepted_with_errors','rejected','failed_transient','failed_validation')",
    )


def register_all_models() -> tuple[str, ...]:
    """Import every active model without mutating its declared metadata."""
    modules = CORE_MODEL_MODULES + discover_module_model_modules()
    for module_name in modules:
        import_module(module_name)
    return modules


def build_migration_metadata() -> MetaData:
    """Return an isolated production-equivalent metadata view for Alembic."""
    register_all_models()

    migration_metadata = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(migration_metadata)

    apply_migration_contract(migration_metadata)
    return migration_metadata
