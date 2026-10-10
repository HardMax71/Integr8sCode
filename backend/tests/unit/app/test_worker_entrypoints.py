import importlib
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

from app.settings import Settings

pytestmark = pytest.mark.unit

_Hook = Callable[[], Awaitable[None]]

WORKERS = {
    "run_dlq_processor": ("create_dlq_processor_container", True),
    "run_event_replay": ("create_event_replay_container", True),
    "run_k8s_worker": ("create_k8s_worker_container", False),
    "run_pod_monitor": ("create_pod_monitor_container", True),
    "run_result_processor": ("create_result_processor_container", False),
    "run_saga_orchestrator": ("create_saga_orchestrator_container", True),
}


@pytest.mark.parametrize(("worker", "factory", "has_scheduler"), [(w, f, s) for w, (f, s) in WORKERS.items()])
async def test_container_closes_after_the_broker_stops(
    monkeypatch: pytest.MonkeyPatch, test_settings: Settings, worker: str, factory: str, has_scheduler: bool
) -> None:
    module = importlib.import_module(f"workers.{worker}")
    order: list[str] = []

    class FakeFastStream:
        """Calls the hooks in FastStream 0.7's order: on_shutdown, broker.stop(), after_shutdown."""

        def __init__(
            self,
            broker: object,
            *,
            on_startup: Sequence[_Hook] = (),
            on_shutdown: Sequence[_Hook] = (),
            after_shutdown: Sequence[_Hook] = (),
        ) -> None:
            self.hooks = (on_startup, on_shutdown, after_shutdown)

        async def run(self) -> None:
            on_startup, on_shutdown, after_shutdown = self.hooks
            for hook in on_startup:
                await hook()
            for hook in on_shutdown:
                await hook()
            order.append("broker.stop")
            for hook in after_shutdown:
                await hook()

    container = MagicMock()
    container.get = AsyncMock(return_value=AsyncMock())
    container.close = AsyncMock(side_effect=lambda: order.append("container.close"))
    scheduler = MagicMock()
    scheduler.shutdown.side_effect = lambda **_: order.append("scheduler.shutdown")
    runs: list[Coroutine[Any, Any, None]] = []

    monkeypatch.setattr(module, "asyncio", SimpleNamespace(run=runs.append))
    monkeypatch.setattr(module, "Settings", lambda **_: test_settings)
    monkeypatch.setattr(module, "setup_logger", lambda _level: structlog.get_logger("test"))
    monkeypatch.setattr(module, "setup_log_exporter", MagicMock())
    monkeypatch.setattr(module, "AsyncMongoClient", MagicMock())
    monkeypatch.setattr(module, "init_beanie", AsyncMock())
    monkeypatch.setattr(module, factory, lambda _settings: container)
    monkeypatch.setattr(module, "setup_dishka", MagicMock())
    monkeypatch.setattr(module, "FastStream", FakeFastStream)
    for name in dir(module):
        if name.startswith("register_"):
            monkeypatch.setattr(module, name, MagicMock())
    if has_scheduler:
        monkeypatch.setattr(module, "AsyncIOScheduler", lambda: scheduler)

    module.main()
    await runs[0]

    expected = ["broker.stop", "container.close"]
    assert order == (["scheduler.shutdown", *expected] if has_scheduler else expected)
