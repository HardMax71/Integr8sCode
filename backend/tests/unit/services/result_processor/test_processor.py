import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.metrics import ExecutionMetrics
from app.domain.enums.execution import ExecutionStatus
from app.domain.events.typed import (
    EventMetadata,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
    ResourceUsageDomain,
)
from app.domain.execution import ExecutionNotFoundError
from app.domain.execution.models import DomainExecution
from app.services.result_processor.processor import ResultProcessor

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.services.result_processor.processor")

_METADATA = EventMetadata(service_name="tests", service_version="1.0.0")


def _make_processor(
    execution_metrics: ExecutionMetrics,
    exec_repo: AsyncMock | None = None,
    producer: AsyncMock | None = None,
) -> ResultProcessor:
    settings = MagicMock()
    settings.K8S_POD_MEMORY_LIMIT = "256Mi"
    return ResultProcessor(
        execution_repo=exec_repo or AsyncMock(),
        producer=producer or AsyncMock(),
        settings=settings,
        logger=_test_logger,
        execution_metrics=execution_metrics,
    )


class TestHandlerTypeGuards:
    """Handlers must reject wrong event types with TypeError."""

    async def test_completed_rejects_wrong_type(self, execution_metrics: ExecutionMetrics) -> None:
        processor = _make_processor(execution_metrics)
        wrong = ExecutionFailedEvent(execution_id="e1", exit_code=1, metadata=_METADATA)
        with pytest.raises(TypeError, match="Expected ExecutionCompletedEvent"):
            await processor.handle_execution_completed(wrong)

    async def test_failed_rejects_wrong_type(self, execution_metrics: ExecutionMetrics) -> None:
        processor = _make_processor(execution_metrics)
        wrong = ExecutionCompletedEvent(execution_id="e1", exit_code=0, metadata=_METADATA)
        with pytest.raises(TypeError, match="Expected ExecutionFailedEvent"):
            await processor.handle_execution_failed(wrong)

    async def test_timeout_rejects_wrong_type(self, execution_metrics: ExecutionMetrics) -> None:
        processor = _make_processor(execution_metrics)
        wrong = ExecutionCompletedEvent(execution_id="e1", exit_code=0, metadata=_METADATA)
        with pytest.raises(TypeError, match="Expected ExecutionTimeoutEvent"):
            await processor.handle_execution_timeout(wrong)


class TestHandleExecutionCompleted:
    async def test_raises_when_execution_not_found(self, execution_metrics: ExecutionMetrics) -> None:
        repo = AsyncMock()
        repo.get_execution.return_value = None
        processor = _make_processor(execution_metrics, exec_repo=repo)

        event = ExecutionCompletedEvent(execution_id="missing", exit_code=0, metadata=_METADATA)
        with pytest.raises(ExecutionNotFoundError):
            await processor.handle_execution_completed(event)

    async def test_stores_result_and_publishes(self, execution_metrics: ExecutionMetrics) -> None:
        repo = AsyncMock()
        repo.get_execution.return_value = DomainExecution(
            execution_id="e1", lang="python", lang_version="3.11"
        )
        repo.write_terminal_result.return_value = True
        producer = AsyncMock()
        processor = _make_processor(execution_metrics, exec_repo=repo, producer=producer)

        event = ExecutionCompletedEvent(
            execution_id="e1", exit_code=0, stdout="ok", stderr="", metadata=_METADATA,
            resource_usage=ResourceUsageDomain(execution_time_wall_seconds=1.5, peak_memory_kb=51200),
        )
        await processor.handle_execution_completed(event)

        repo.write_terminal_result.assert_awaited_once()
        result_arg = repo.write_terminal_result.call_args[0][0]
        assert result_arg.execution_id == "e1"
        assert result_arg.status == ExecutionStatus.COMPLETED
        assert result_arg.exit_code == 0
        producer.produce.assert_awaited_once()


class TestHandleExecutionFailed:
    async def test_stores_result_and_publishes(self, execution_metrics: ExecutionMetrics) -> None:
        repo = AsyncMock()
        repo.get_execution.return_value = DomainExecution(
            execution_id="e2", lang="python", lang_version="3.11"
        )
        repo.write_terminal_result.return_value = True
        producer = AsyncMock()
        processor = _make_processor(execution_metrics, exec_repo=repo, producer=producer)

        event = ExecutionFailedEvent(
            execution_id="e2", exit_code=1, stderr="error", metadata=_METADATA
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
        repo.get_execution.return_value = DomainExecution(
            execution_id="e3", lang="python", lang_version="3.11"
        )
        repo.write_terminal_result.return_value = True
        producer = AsyncMock()
        processor = _make_processor(execution_metrics, exec_repo=repo, producer=producer)

        event = ExecutionTimeoutEvent(
            execution_id="e3", timeout_seconds=30, metadata=_METADATA
        )
        await processor.handle_execution_timeout(event)

        repo.write_terminal_result.assert_awaited_once()
        result_arg = repo.write_terminal_result.call_args[0][0]
        assert result_arg.execution_id == "e3"
        assert result_arg.status == ExecutionStatus.TIMEOUT
        assert result_arg.exit_code == -1
        producer.produce.assert_awaited_once()
