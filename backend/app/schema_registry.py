"""Authoritative SQLAlchemy model registration for migration/schema checks.

Alembic autogenerate and schema-parity validation only see tables whose model
modules have been imported into ``Base.metadata``. DentalPin is modular, so
keeping a hand-written list of every module model in ``alembic/env.py`` is
fragile and previously left active tables out of the metadata contract.

This registry keeps the few core model modules explicit and discovers every
``app/modules/<name>/models.py`` file deterministically. Importing a module is
sufficient to register its declarative models with ``Base.metadata``.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

CORE_MODEL_MODULES: tuple[str, ...] = (
    "app.core.agents.models",
    "app.core.auth.models",
    "app.core.plugins.db_models",
)

MODULES_ROOT = Path(__file__).resolve().parent / "modules"


def discover_module_model_modules() -> tuple[str, ...]:
    """Return every active module package that defines ``models.py``."""
    return tuple(
        f"app.modules.{entry.name}.models"
        for entry in sorted(MODULES_ROOT.iterdir(), key=lambda path: path.name)
        if entry.is_dir() and (entry / "models.py").is_file()
    )


def register_all_models() -> tuple[str, ...]:
    """Import the complete model set and return the imported module names."""
    modules = CORE_MODEL_MODULES + discover_module_model_modules()
    for module_name in modules:
        import_module(module_name)
    return modules
