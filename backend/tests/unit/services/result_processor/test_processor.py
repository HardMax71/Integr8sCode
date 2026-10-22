from unittest.mock import AsyncMock

import pytest
import structlog
from aiokafka.errors import KafkaError
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pymongo.errors import PyMongoError

from app.db import EventRepository
from app.db.docs import ExecutionDocument
from app.domain.admin import SystemSettings
from app.domain.enums import EventType, ExecutionErrorType, ExecutionStatus
from app.domain.events import (
    EventMetadata,
    ExecutionCancelledEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
    PodRunningEvent,
    PodScheduledEvent,
    ResourceUsageDomain,
)
from app.events import UnifiedProducer
from app.events.core.transport import KafkaEventTransport
from app.runtime_registry import POD_RUNTIME_CONFIGS, parse_quantity
from app.services.result_processor import ResultProcessor
from app.services.runtime_settings import RuntimeSettingsLoader
from app.settings import Settings

pytestmark = pytest.mark.unit

_test_logger = structlog.get_logger("test.services.result_processor.processor")

_METADATA = EventMetadata(service_name="tests", service_version="1.0.0", user_id="u1")


def _make_processor(
    tracer: trace.Tracer,
    exec_repo: AsyncMock | None = None,
    producer: UnifiedProducer | None = None,
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
        tracer=tracer,
    )


class TestHandleExecutionCompleted:
    async def test_skips_a_deleted_execution(self, tracer: trace.Tracer) -> None:
        repo = AsyncMock()
        repo.get_execution.return_value = None
        producer = AsyncMock()
        processor = _make_processor(tracer, exec_repo=repo, producer=producer)

        event = ExecutionCompletedEvent(
            execution_id="missing", exit_code=0, resource_usage=ResourceUsageDomain(), metadata=_METADATA
        )
        await processor.handle_execution_completed(event)

        repo.write_terminal_result.assert_not_awaited()
        producer.produce.assert_not_awaited()
        producer.produce_or_log.assert_not_awaited()

    async def test_stores_result_and_publishes(self, tracer: trace.Tracer, span_exporter: InMemorySpanExporter) -> None:
        repo = AsyncMock()
        repo.get_execution.return_value = ExecutionDocument(
            script="x", execution_id="e1", lang="python", lang_version="3.11"
        )
        repo.write_terminal_result.return_value = True
        producer = AsyncMock()
        processor = _make_processor(tracer, exec_repo=repo, producer=producer)

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
        assert [c.kwargs["event_to_produce"].event_type for c in producer.produce_or_log.await_args_list] == [
            EventType.EXECUTION_COMPLETED,
            EventType.RESULT_STORED,
        ]
        [span] = span_exporter.get_finished_spans()
        assert (span.name, span.attributes) == (
            "execution.result",
            {
                "execution.status": "completed",
                "execution.lang_and_version": "python-3.11",
                "execution.runtime_seconds": 1.5,
                "execution.memory_mib": 50.0,
                "execution.memory_percent": 50 / 256 * 100,
            },
        )

    @pytest.mark.parametrize(
        ("lang", "peak_memory_kb", "expected_percent"),
        [
            ("python", 64 * 1024, 50.0),
            ("go", int(parse_quantity(POD_RUNTIME_CONFIGS["go"].min_memory)) // 2048, 50.0),
        ],
    )
    async def test_memory_percent_uses_effective_language_limit(
        self,
        tracer: trace.Tracer,
        span_exporter: InMemorySpanExporter,
        lang: str,
        peak_memory_kb: int,
        expected_percent: float,
    ) -> None:
        repo = AsyncMock()
        repo.get_execution.return_value = ExecutionDocument(script="x", execution_id="e1", lang=lang, lang_version="1")
        processor = _make_processor(tracer, exec_repo=repo, admin_memory_limit="128Mi")

        event = ExecutionCompletedEvent(
            execution_id="e1",
            exit_code=0,
            metadata=_METADATA,
            resource_usage=ResourceUsageDomain(peak_memory_kb=peak_memory_kb),
        )
        await processor.handle_execution_completed(event)

        [span] = span_exporter.get_finished_spans()
        assert span.attributes is not None
        assert span.attributes["execution.memory_percent"] == pytest.approx(expected_percent)


class TestHandleExecutionFailed:
    async def test_stores_result_and_publishes(self, tracer: trace.Tracer, span_exporter: InMemorySpanExporter) -> None:
        repo = AsyncMock()
        repo.get_execution.return_value = ExecutionDocument(
            script="x", execution_id="e2", lang="python", lang_version="3.11"
        )
        repo.write_terminal_result.return_value = True
        producer = AsyncMock()
        processor = _make_processor(tracer, exec_repo=repo, producer=producer)

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
        assert [c.kwargs["event_to_produce"].event_type for c in producer.produce_or_log.await_args_list] == [
            EventType.EXECUTION_FAILED,
            EventType.RESULT_STORED,
        ]
        [span] = span_exporter.get_finished_spans()
        assert span.attributes == {
            "execution.status": "failed",
            "execution.lang_and_version": "python-3.11",
            "execution.error_type": "script_error",
        }


class TestHandleExecutionTimeout:
    async def test_stores_result_and_publishes(self, tracer: trace.Tracer, span_exporter: InMemorySpanExporter) -> None:
        repo = AsyncMock()
        repo.get_execution.return_value = ExecutionDocument(
            script="x", execution_id="e3", lang="python", lang_version="3.11"
        )
        repo.write_terminal_result.return_value = True
        producer = AsyncMock()
        processor = _make_processor(tracer, exec_repo=repo, producer=producer)

        event = ExecutionTimeoutEvent(
            execution_id="e3", timeout_seconds=30, resource_usage=ResourceUsageDomain(), metadata=_METADATA
        )
        await processor.handle_execution_timeout(event)

        repo.write_terminal_result.assert_awaited_once()
        result_arg = repo.write_terminal_result.call_args[0][0]
        assert result_arg.execution_id == "e3"
        assert result_arg.status == ExecutionStatus.TIMEOUT
        assert result_arg.exit_code == -1
        assert [c.kwargs["event_to_produce"].event_type for c in producer.produce_or_log.await_args_list] == [
            EventType.EXECUTION_TIMEOUT,
            EventType.RESULT_STORED,
        ]
        [span] = span_exporter.get_finished_spans()
        assert span.attributes == {
            "execution.status": "timeout",
            "execution.lang_and_version": "python-3.11",
            "execution.error_type": "timeout",
            "execution.runtime_seconds": 30,
        }


class TestResultForAFinishedExecution:
    """A cancelled execution's pod fails when it's deleted, and that late result must not reach anyone."""

    async def test_publishes_nothing_when_the_execution_already_ended(self, tracer: trace.Tracer) -> None:
        repo = AsyncMock()
        repo.get_execution.return_value = ExecutionDocument(
            script="x", execution_id="e4", lang="python", lang_version="3.11"
        )
        repo.write_terminal_result.return_value = False
        producer = AsyncMock()
        processor = _make_processor(tracer, exec_repo=repo, producer=producer)

        event = ExecutionFailedEvent(
            execution_id="e4", exit_code=143, error_type=ExecutionErrorType.SCRIPT_ERROR, metadata=_METADATA
        )
        await processor.handle_execution_failed(event)

        repo.write_terminal_result.assert_awaited_once()
        producer.produce.assert_not_awaited()
        producer.produce_or_log.assert_not_awaited()


class TestHandleExecutionCancelled:
    async def test_stores_cancelled_and_publishes_result_stored(
        self, tracer: trace.Tracer, span_exporter: InMemorySpanExporter
    ) -> None:
        repo = AsyncMock()
        repo.get_execution.return_value = ExecutionDocument(
            script="x", execution_id="e5", lang="python", lang_version="3.11"
        )
        repo.write_terminal_result.return_value = True
        producer = AsyncMock()
        processor = _make_processor(tracer, exec_repo=repo, producer=producer)

        await processor.handle_execution_cancelled(
            ExecutionCancelledEvent(execution_id="e5", cancelled_by="u1", metadata=_METADATA)
        )

        result_arg = repo.write_terminal_result.call_args[0][0]
        assert (result_arg.execution_id, result_arg.status, result_arg.exit_code) == (
            "e5",
            ExecutionStatus.CANCELLED,
            None,
        )
        assert [c.kwargs["event_to_produce"].event_type for c in producer.produce_or_log.await_args_list] == [
            EventType.RESULT_STORED
        ]
        [span] = span_exporter.get_finished_spans()
        assert span.attributes == {"execution.status": "cancelled", "execution.lang_and_version": "python-3.11"}


class TestKafkaOutage:
    """After the write a Kafka error is only logged, so the pod monitor still deletes the pod and frees the slot."""

    async def test_publish_failure_after_the_write_is_not_raised(self, tracer: trace.Tracer) -> None:
        repo = AsyncMock()
        repo.get_execution.return_value = ExecutionDocument(
            script="x", execution_id="e6", lang="python", lang_version="3.11"
        )
        repo.write_terminal_result.return_value = True
        transport = AsyncMock(spec=KafkaEventTransport)
        transport.publish.side_effect = KafkaError("broker down")
        producer = UnifiedProducer(AsyncMock(spec=EventRepository), transport, _test_logger, tracer)
        processor = _make_processor(tracer, exec_repo=repo, producer=producer)

        await processor.handle_execution_completed(
            ExecutionCompletedEvent(
                execution_id="e6", exit_code=0, resource_usage=ResourceUsageDomain(), metadata=_METADATA
            )
        )

        repo.write_terminal_result.assert_awaited_once()
        assert [c.args[1] for c in transport.publish.await_args_list] == [
            EventType.EXECUTION_COMPLETED,
            EventType.RESULT_STORED,
        ]

    async def test_failed_write_publishes_result_failed(self, tracer: trace.Tracer) -> None:
        repo = AsyncMock()
        repo.get_execution.return_value = ExecutionDocument(
            script="x", execution_id="e7", lang="python", lang_version="3.11"
        )
        repo.write_terminal_result.side_effect = PyMongoError("mongo down")
        producer = AsyncMock()
        processor = _make_processor(tracer, exec_repo=repo, producer=producer)

        await processor.handle_execution_completed(
            ExecutionCompletedEvent(
                execution_id="e7", exit_code=0, resource_usage=ResourceUsageDomain(), metadata=_METADATA
            )
        )

        assert [c.kwargs["event_to_produce"].event_type for c in producer.produce.await_args_list] == [
            EventType.RESULT_FAILED
        ]
        producer.produce_or_log.assert_not_awaited()


class TestLostRequest:
    async def test_stores_a_system_error_for_the_owner(self, tracer: trace.Tracer) -> None:
        repo = AsyncMock()
        repo.get_execution.return_value = ExecutionDocument(
            script="x", execution_id="e8", lang="python", lang_version="3.11", user_id="owner"
        )
        repo.write_terminal_result.return_value = True
        producer = AsyncMock()
        processor = _make_processor(tracer, exec_repo=repo, producer=producer)

        await processor.handle_lost_request("e8")

        result = repo.write_terminal_result.call_args[0][0]
        assert (result.status, result.error_type, result.exit_code) == (
            ExecutionStatus.FAILED,
            ExecutionErrorType.SYSTEM_ERROR,
            -1,
        )
        [failed, stored] = [c.kwargs["event_to_produce"] for c in producer.produce_or_log.await_args_list]
        assert (failed.event_type, failed.metadata.user_id) == (EventType.EXECUTION_FAILED, "owner")
        assert stored.event_type == EventType.RESULT_STORED

    async def test_skips_a_deleted_execution(self, tracer: trace.Tracer) -> None:
        repo = AsyncMock()
        repo.get_execution.return_value = None
        processor = _make_processor(tracer, exec_repo=repo)

        await processor.handle_lost_request("gone")

        repo.write_terminal_result.assert_not_awaited()


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
        self, tracer: trace.Tracer, event: PodScheduledEvent | PodRunningEvent, status: ExecutionStatus
    ) -> None:
        repo = AsyncMock()
        processor = _make_processor(tracer, exec_repo=repo)

        await processor.handle_pod_progress(event)

        repo.advance_status.assert_awaited_once_with("e1", status)
