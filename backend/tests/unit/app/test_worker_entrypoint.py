from collections.abc import Awaitable, Callable, Coroutine, Sequence
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

from app import worker as module
from app.settings import Settings

pytestmark = pytest.mark.unit

_Hook = Callable[[], Awaitable[None]]


async def test_worker_wires_routers_and_jobs_and_closes_the_container_last(
    monkeypatch: pytest.MonkeyPatch, test_settings: Settings
) -> None:
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
    dependency = AsyncMock()
    dependency.include_routers = MagicMock()
    container.get = AsyncMock(return_value=dependency)
    container.close = AsyncMock(side_effect=lambda: order.append("container.close"))
    scheduler = MagicMock()
    scheduler.shutdown.side_effect = lambda **_: order.append("scheduler.shutdown")
    runs: list[Coroutine[Any, Any, None]] = []

    monkeypatch.setattr(module, "asyncio", SimpleNamespace(run=runs.append))
    monkeypatch.setattr(module, "Settings", lambda **_: test_settings)
    monkeypatch.setattr(module, "setup_logger", lambda _level: structlog.get_logger("test"))
    monkeypatch.setattr(module, "setup_log_exporter", MagicMock())
    monkeypatch.setattr(module, "setup_metrics", MagicMock())
    monkeypatch.setattr(module, "AsyncMongoClient", MagicMock())
    monkeypatch.setattr(module, "init_beanie", AsyncMock())
    monkeypatch.setattr(module, "create_worker_container", lambda _settings: container)
    monkeypatch.setattr(module, "setup_dishka", MagicMock())
    monkeypatch.setattr(module, "FastStream", FakeFastStream)
    monkeypatch.setattr(module, "AsyncIOScheduler", lambda: scheduler)

    module.main()
    await runs[0]

    assert order == ["scheduler.shutdown", "broker.stop", "container.close"]
    assert len(dependency.include_routers.call_args.args) == 3
    assert [c.kwargs["id"] for c in scheduler.add_job.call_args_list] == [
        "pod_monitor_watch",
        "saga_try_schedule",
        "saga_check_timeouts",
        "dlq_monitor_retries",
    ]
