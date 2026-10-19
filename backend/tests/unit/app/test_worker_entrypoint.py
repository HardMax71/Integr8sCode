from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from faststream.kafka import KafkaBroker

from app import worker as module
from app.settings import Settings

pytestmark = pytest.mark.unit


async def test_run_wires_the_routers_and_orders_shutdown(
    monkeypatch: pytest.MonkeyPatch, test_settings: Settings
) -> None:
    broker = MagicMock(spec=KafkaBroker)
    container = MagicMock()
    container.get = AsyncMock(return_value=broker)
    scheduler = MagicMock()
    fast_stream = MagicMock()
    fast_stream.return_value.run = AsyncMock()
    monkeypatch.setattr(module, "AsyncMongoClient", MagicMock())
    monkeypatch.setattr(module, "init_beanie", AsyncMock())
    monkeypatch.setattr(module, "create_worker_container", MagicMock(return_value=container))
    monkeypatch.setattr(module, "setup_dishka", MagicMock())
    monkeypatch.setattr(module, "start_jobs", AsyncMock(return_value=scheduler))
    monkeypatch.setattr(module, "FastStream", fast_stream)

    await module.run(test_settings, structlog.get_logger("test"))

    assert len(broker.include_routers.call_args.args) == 3
    fast_stream.assert_called_once_with(broker, on_shutdown=[scheduler.shutdown], after_shutdown=[container.close])
    fast_stream.return_value.run.assert_awaited_once()


async def test_start_jobs_prepares_the_cluster_and_schedules_the_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    dependency = AsyncMock()
    container = MagicMock()
    container.get = AsyncMock(return_value=dependency)
    scheduler = MagicMock()
    monkeypatch.setattr(module, "AsyncIOScheduler", MagicMock(return_value=scheduler))

    assert await module.start_jobs(container) is scheduler

    dependency.ensure_namespace_security.assert_awaited_once()
    dependency.ensure_image_pre_puller_daemonset.assert_awaited_once()
    assert [c.kwargs["id"] for c in scheduler.add_job.call_args_list] == [
        "pod_monitor_watch",
        "saga_try_schedule",
        "saga_check_timeouts",
        "dlq_monitor_retries",
        "idempotency_report_keys",
    ]
    scheduler.start.assert_called_once()
