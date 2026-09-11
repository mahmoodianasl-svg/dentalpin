"""Module registry for tracking loaded modules."""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BaseModule

logger = logging.getLogger(__name__)


class ModuleRegistry:
    """Registry that separates discovered code from active modules.

    Discovery is an inventory concern: administrators must be able to see and
    install code that exists on disk. Activation is a security boundary: only
    modules whose persisted state is ``installed`` may contribute runtime
    capabilities.
    """

    def __init__(self) -> None:
        self._discovered: dict[str, BaseModule] = {}
        self._modules: dict[str, BaseModule] = {}

    def register_discovered(self, module: "BaseModule") -> None:
        """Add module code to the administrative discovery catalog only."""
        existing = self._discovered.get(module.name)
        if existing is not None and existing is not module:
            raise ValueError(f"Module '{module.name}' is already discovered")
        self._discovered[module.name] = module

    def register(self, module: "BaseModule") -> None:
        """Activate a discovered module instance."""
        if module.name in self._modules:
            raise ValueError(f"Module '{module.name}' is already registered")
        self.register_discovered(module)
        self._modules[module.name] = module
        # Drop the role-permission cache so the merge picks up the
        # newly-registered module's manifest grants on next lookup.
        from app.core.auth.permissions import invalidate_role_permissions_cache

        invalidate_role_permissions_cache()
        logger.info(f"Registered module: {module.name} v{module.version}")

    def get(self, name: str) -> "BaseModule | None":
        """Get an active module by name, or ``None`` if inactive."""
        return self._modules.get(name)

    def get_discovered(self, name: str) -> "BaseModule | None":
        """Get module code regardless of persisted activation state."""
        return self._discovered.get(name)

    def is_loaded(self, name: str) -> bool:
        """Compatibility alias for :meth:`is_installed`."""
        return self.is_installed(name)

    def is_installed(self, name: str) -> bool:
        """Check whether a module is active in this process."""
        return name in self._modules

    def is_discovered(self, name: str) -> bool:
        """Check whether module code exists, regardless of activation."""
        return name in self._discovered

    def list_modules(self) -> list["BaseModule"]:
        """Return active modules only."""
        return list(self._modules.values())

    def list_discovered(self) -> list["BaseModule"]:
        """Return all discovered module code for lifecycle administration."""
        return list(self._discovered.values())

    def get_all_permissions(self) -> list[str]:
        """Return all permissions from all loaded modules, fully namespaced.

        Each permission is prefixed with the module name:
        'patients.read' from 'clinical' module becomes 'clinical.patients.read'
        """
        permissions: list[str] = []
        for module in self._modules.values():
            for perm in module.get_permissions():
                permissions.append(f"{module.name}.{perm}")
        return permissions


# Global singleton instance
module_registry = ModuleRegistry()
