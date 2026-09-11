"""W1/ARCH-001 persisted module activation security boundary."""

from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.core.plugins import loader
from app.core.plugins.base import BaseModule
from app.core.plugins.registry import ModuleRegistry
from app.core.scheduling import ScheduledJob


class _RuntimeModule(BaseModule):
    def __init__(self, name: str, dependencies: list[str] | None = None) -> None:
        self._name = name
        self._dependencies = dependencies or []

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    @property
    def version(self) -> str:  # type: ignore[override]
        return "1.0.0"

    @property
    def dependencies(self) -> list[str]:  # type: ignore[override]
        return self._dependencies

    def get_models(self) -> list:
        return []

    def get_router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/probe")
        async def probe() -> dict[str, str]:
            return {"module": self.name}

        return router

    def get_permissions(self) -> list[str]:
        return ["probe.read"]

    def get_event_handlers(self) -> dict[str, object]:
        return {f"{self.name}.probe": lambda _: None}

    def get_tools(self) -> list:
        return []

    def get_scheduled_jobs(self) -> list[ScheduledJob]:
        return [
            ScheduledJob(
                id=f"{self.name}.probe",
                func=lambda: None,
                trigger="interval",
                trigger_args={"minutes": 5},
                name=f"{self.name} probe",
            )
        ]


def test_only_persisted_installed_modules_gain_runtime_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = _RuntimeModule("active")
    inactive = _RuntimeModule("inactive")
    registry = ModuleRegistry()
    registered_tools: list[str] = []
    subscribed_events: list[str] = []

    monkeypatch.setattr(loader, "module_registry", registry)
    monkeypatch.setattr(loader, "discover_modules", lambda: [inactive, active])

    from app.core import events as events_module
    from app.core.agents.tools import registry as tools_registry_module

    monkeypatch.setattr(
        tools_registry_module.tool_registry,
        "register_from",
        lambda module: registered_tools.append(module.name),
    )
    monkeypatch.setattr(
        events_module.event_bus,
        "subscribe",
        lambda event_type, _handler: subscribed_events.append(event_type),
    )

    app = FastAPI()
    loader.load_modules(app, installed_names={"active"})

    assert {module.name for module in registry.list_discovered()} == {"active", "inactive"}
    assert [module.name for module in registry.list_modules()] == ["active"]
    assert registry.get("inactive") is None
    assert registry.get_discovered("inactive") is inactive
    assert registry.get_all_permissions() == ["active.probe.read"]
    assert registered_tools == ["active"]
    assert subscribed_events == ["active.probe"]

    from app.core import scheduler as scheduler_module

    scheduled_jobs: list[str] = []

    class _Scheduler:
        running = False

        def get_job(self, _job_id: str) -> None:
            return None

        def add_job(self, _func: object, _trigger: object, *, id: str, **_kwargs: object) -> None:
            scheduled_jobs.append(id)

        def start(self) -> None:
            self.running = True

    scheduler = _Scheduler()
    monkeypatch.setattr(scheduler_module, "module_registry", registry)
    monkeypatch.setattr(scheduler_module.settings, "TESTING", False)
    monkeypatch.setattr(scheduler_module, "scheduler", None)
    monkeypatch.setattr(scheduler_module, "get_scheduler", lambda: scheduler)
    scheduler_module.init_scheduler()
    assert scheduled_jobs == ["active.probe"]

    with TestClient(app) as client:
        assert client.get("/api/v1/active/probe").status_code == 200
        assert client.get("/api/v1/inactive/probe").status_code == 404


def test_activation_rejects_incomplete_persisted_dependency_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependency = _RuntimeModule("dependency")
    dependent = _RuntimeModule("dependent", ["dependency"])
    registry = ModuleRegistry()
    registry.register_discovered(dependency)
    registry.register_discovered(dependent)
    monkeypatch.setattr(loader, "module_registry", registry)

    app = FastAPI()
    with pytest.raises(RuntimeError, match="dependent requires dependency"):
        loader.activate_modules(app, {"dependent"})

    assert registry.list_modules() == []
    with TestClient(app) as client:
        assert client.get("/api/v1/dependent/probe").status_code == 404


@pytest.mark.asyncio
async def test_startup_does_not_activate_modules_when_state_read_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main as main_module

    activated = False

    class _BrokenSessionContext:
        async def __aenter__(self) -> None:
            raise OSError("database unavailable")

        async def __aexit__(self, *_args: object) -> None:
            return None

    def _record_activation(_app: FastAPI, _names: set[str]) -> None:
        nonlocal activated
        activated = True

    monkeypatch.setattr(main_module, "discover_module_catalog", lambda: [])
    monkeypatch.setattr(main_module, "async_session_maker", lambda: _BrokenSessionContext())
    monkeypatch.setattr(main_module, "activate_modules", _record_activation)

    with pytest.raises(RuntimeError, match="Persisted module activation state is unavailable"):
        async with main_module.lifespan(FastAPI()):
            pytest.fail("startup must not reach the serving state")

    assert activated is False
