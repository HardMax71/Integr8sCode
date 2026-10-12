from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

from app.core.metrics import ExecutionMetrics
from app.domain.admin import SystemSettings
from app.domain.enums import ExecutionErrorType, ExecutionStatus
from app.domain.events import (
    EventMetadata,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
    PodRunningEvent,
    PodScheduledEvent,
    ResourceUsageDomain,
)
from app.domain.execution import ExecutionNotFoundError
from app.domain.execution.models import DomainExecution
from app.services.result_processor import ResultProcessor
from app.services.runtime_settings import RuntimeSettingsLoader
from app.settings import Settings

pytestmark = pytest.mark.unit

_test_logger = structlog.get_logger("test.services.result_processor.processor")

_METADATA = EventMetadata(service_name="tests", service_version="1.0.0", user_id="u1")


def _make_processor(
    execution_metrics: ExecutionMetrics,
    exec_repo: AsyncMock | None = None,
    producer: AsyncMock | None = None,
    admin_memory_limit: str = "256Mi",
) -> ResultProcessor:
    settings_repo = AsyncMock()
    settings_repo.get_system_settings.return_value = SystemSettings(memory_limit=admin_memory_limit)
    runtime_settings = RuntimeSettingsLoader(
        repo=settings_repo, settings=Settings(config_path="config.test.toml"), logger=_test_logger
    )
    return ResultProcessor(
        execution_repo=exec_repo or AsyncMock(),
        producer=producer or AsyncMock(),
        runtime_settings=runtime_settings,
        logger=_test_logger,
        execution_metrics=execution_metrics,
    )


class TestHandlerTypeGuards:
    """Handlers must reject wrong event types with TypeError."""

    async def test_completed_rejects_wrong_type(self, execution_metrics: ExecutionMetrics) -> None:
        processor = _make_processor(execution_metrics)
        wrong = ExecutionFailedEvent(
            execution_id="e1", exit_code=1, error_type=ExecutionErrorType.SCRIPT_ERROR, metadata=_METADATA
        )
        with pytest.raises(TypeError, match="Expected ExecutionCompletedEvent"):
            await processor.handle_execution_completed(wrong)

    async def test_failed_rejects_wrong_type(self, execution_metrics: ExecutionMetrics) -> None:
        processor = _make_processor(execution_metrics)
        wrong = ExecutionCompletedEvent(
            execution_id="e1", exit_code=0, resource_usage=ResourceUsageDomain(), metadata=_METADATA
        )
        with pytest.raises(TypeError, match="Expected ExecutionFailedEvent"):
            await processor.handle_execution_failed(wrong)

    async def test_timeout_rejects_wrong_type(self, execution_metrics: ExecutionMetrics) -> None:
        processor = _make_processor(execution_metrics)
        wrong = ExecutionCompletedEvent(
            execution_id="e1", exit_code=0, resource_usage=ResourceUsageDomain(), metadata=_METADATA
        )
        with pytest.raises(TypeError, match="Expected ExecutionTimeoutEvent"):
            await processor.handle_execution_timeout(wrong)


class TestHandleExecutionCompleted:
    async def test_raises_when_execution_not_found(self, execution_metrics: ExecutionMetrics) -> None:
        repo = AsyncMock()
        repo.get_execution.return_value = None
        processor = _make_processor(execution_metrics, exec_repo=repo)

        event = ExecutionCompletedEvent(
            execution_id="missing", exit_code=0, resource_usage=ResourceUsageDomain(), metadata=_METADATA
        )
        with pytest.raises(ExecutionNotFoundError):
            await processor.handle_execution_completed(event)

    async def test_stores_result_and_publishes(self, execution_metrics: ExecutionMetrics) -> None:
        repo = AsyncMock()
        repo.get_execution.return_value = DomainExecution(execution_id="e1", lang="python", lang_version="3.11")
        repo.write_terminal_result.return_value = True
        producer = AsyncMock()
        processor = _make_processor(execution_metrics, exec_repo=repo, producer=producer)

        event = ExecutionCompletedEvent(
            execution_id="e1",
            exit_code=0,
            stdout="ok",
            stderr="",
            metadata=_METADATA,
            resource_usage=ResourceUsageDomain(execution_time_wall_seconds=1.5, peak_memory_kb=51200),
        )
        await processor.handle_execution_completed(event)

        repo.write_terminal_result.assert_awaited_once()
        result_arg = repo.write_terminal_result.call_args[0][0]
        assert result_arg.execution_id == "e1"
        assert result_arg.status == ExecutionStatus.COMPLETED
        assert result_arg.exit_code == 0
        producer.produce.assert_awaited_once()

    @pytest.mark.parametrize(
        ("lang", "peak_memory_kb", "expected_percent"),
        [
            ("python", 64 * 1024, 50.0),
            ("go", 160 * 1024, 50.0),
        ],
    )
    async def test_memory_percent_uses_effective_language_limit(
        self, execution_metrics: ExecutionMetrics, lang: str, peak_memory_kb: int, expected_percent: float
    ) -> None:
        repo = AsyncMock()
        repo.get_execution.return_value = DomainExecution(execution_id="e1", lang=lang, lang_version="1")
        metrics = MagicMock(spec=execution_metrics)
        processor = _make_processor(metrics, exec_repo=repo, admin_memory_limit="128Mi")

        event = ExecutionCompletedEvent(
            execution_id="e1",
            exit_code=0,
            metadata=_METADATA,
            resource_usage=ResourceUsageDomain(peak_memory_kb=peak_memory_kb),
        )
        await processor.handle_execution_completed(event)

        recorded_percent = metrics.memory_utilization_percent.record.call_args.args[0]
        assert recorded_percent == pytest.approx(expected_percent)


class TestHandleExecutionFailed:
    async def test_stores_result_and_publishes(self, execution_metrics: ExecutionMetrics) -> None:
        repo = AsyncMock()
        repo.get_execution.return_value = DomainExecution(execution_id="e2", lang="python", lang_version="3.11")
        repo.write_terminal_result.return_value = True
        producer = AsyncMock()
        processor = _make_processor(execution_metrics, exec_repo=repo, producer=producer)

        event = ExecutionFailedEvent(
            execution_id="e2",
            exit_code=1,
            error_type=ExecutionErrorType.SCRIPT_ERROR,
            stderr="error",
            metadata=_METADATA,
        )
        await processor.handle_execution_failed(event)

        repo.write_terminal_result.assert_awaited_once()
        result_arg = repo.write_terminal_result.call_args[0][0]
        assert result_arg.execution_id == "e2"
        assert result_arg.status == ExecutionStatus.FAILED
        assert result_arg.exit_code == 1
        producer.produce.assert_awaited_once()


class TestHandleExecutionTimeout:
    async def test_stores_result_and_publishes(self, execution_metrics: ExecutionMetrics) -> None:
        repo = AsyncMock()
        repo.get_execution.return_value = DomainExecution(execution_id="e3", lang="python", lang_version="3.11")
        repo.write_terminal_result.return_value = True
        producer = AsyncMock()
        processor = _make_processor(execution_metrics, exec_repo=repo, producer=producer)

        event = ExecutionTimeoutEvent(
            execution_id="e3", timeout_seconds=30, resource_usage=ResourceUsageDomain(), metadata=_METADATA
        )
        await processor.handle_execution_timeout(event)

        repo.write_terminal_result.assert_awaited_once()
        result_arg = repo.write_terminal_result.call_args[0][0]
        assert result_arg.execution_id == "e3"
        assert result_arg.status == ExecutionStatus.TIMEOUT
        assert result_arg.exit_code == -1
        producer.produce.assert_awaited_once()


class TestPodProgress:
    """Pod events move the stored execution status forward."""

    @pytest.mark.parametrize(
        ("event", "status"),
        [
            (PodScheduledEvent(execution_id="e1", pod_name="p", metadata=_METADATA), ExecutionStatus.SCHEDULED),
            (PodRunningEvent(execution_id="e1", pod_name="p", metadata=_METADATA), ExecutionStatus.RUNNING),
        ],
    )
    async def test_advances_status(
        self, execution_metrics: ExecutionMetrics, event: PodScheduledEvent | PodRunningEvent, status: ExecutionStatus
    ) -> None:
        repo = AsyncMock()
        processor = _make_processor(execution_metrics, exec_repo=repo)

        await processor.handle_pod_progress(event)

        repo.advance_status.assert_awaited_once_with("e1", status)
