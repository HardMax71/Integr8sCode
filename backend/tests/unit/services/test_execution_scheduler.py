from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.domain.admin import SystemSettings
from app.domain.enums import ExecutionErrorType
from app.domain.events import EventMetadata, ExecutionCancelledEvent, ExecutionFailedEvent, ExecutionRequestedEvent
from app.domain.execution import QueuedRequestLostError
from app.services.execution_queue import ExecutionQueueService
from app.services.execution_scheduler import ExecutionScheduler
from app.services.k8s_worker import KubernetesWorker
from app.services.result_processor import ResultProcessor
from app.services.runtime_settings import RuntimeSettingsLoader

pytestmark = pytest.mark.unit

_METADATA = EventMetadata(service_name="tests", service_version="1.0.0", user_id="u1")


def _requested(execution_id: str) -> ExecutionRequestedEvent:
    return ExecutionRequestedEvent(
        execution_id=execution_id,
        aggregate_id=execution_id,
        script="print(1)",
        language="python",
        language_version="3.14",
        runtime_image="python:3.14-slim",
        runtime_command=["python"],
        runtime_filename="main.py",
        timeout_seconds=30,
        cpu_limit="100m",
        memory_limit="128Mi",
        cpu_request="50m",
        memory_request="64Mi",
        metadata=_METADATA,
    )


def _scheduler(tracer: trace.Tracer, scheduled: list[ExecutionRequestedEvent]) -> tuple[ExecutionScheduler, MagicMock]:
    """A scheduler whose queue hands out ``scheduled`` in order; the returned mock records every dependency call."""
    queue = AsyncMock(spec=ExecutionQueueService)
    queue.try_schedule.side_effect = [*((e.execution_id, e) for e in scheduled), None]
    queue.get_queue_status.return_value = {"queue_depth": 3, "active_count": len(scheduled)}
    runtime_settings = AsyncMock(spec=RuntimeSettingsLoader)
    runtime_settings.get_effective_settings.return_value = SystemSettings(max_concurrent_executions=7)
    calls = MagicMock()
    calls.attach_mock(queue, "queue")
    calls.attach_mock(AsyncMock(spec=KubernetesWorker), "k8s")
    calls.attach_mock(AsyncMock(spec=ResultProcessor), "results")
    scheduler = ExecutionScheduler(
        queue=queue,
        k8s_worker=calls.k8s,
        results=calls.results,
        runtime_settings=runtime_settings,
        logger=structlog.get_logger("test.execution_scheduler"),
        tracer=tracer,
    )
    return scheduler, calls


async def test_a_request_is_queued_and_started_while_slots_are_free(
    tracer: trace.Tracer, span_exporter: InMemorySpanExporter
) -> None:
    first, second = _requested("e1"), _requested("e2")
    scheduler, calls = _scheduler(tracer, [first, second])

    await scheduler.handle_execution_requested(first)

    calls.queue.enqueue.assert_awaited_once_with(first)
    assert calls.queue.try_schedule.await_args_list[0].args == (7,)
    assert [c.args for c in calls.k8s.create_pod.await_args_list] == [(first,), (second,)]
    [span] = [s for s in span_exporter.get_finished_spans() if s.name == "queue.schedule_pending"]
    assert span.attributes == {"queue.depth": 3, "queue.active": 2}


async def test_a_pod_that_cannot_be_created_fails_the_execution_and_frees_its_slots(tracer: trace.Tracer) -> None:
    broken, fine = _requested("e1"), _requested("e2")
    scheduler, calls = _scheduler(tracer, [broken, fine])
    calls.k8s.create_pod.side_effect = [RuntimeError("quota exceeded"), None]

    await scheduler.schedule_pending()

    calls.results.handle_execution_failed.assert_awaited_once()
    failed: ExecutionFailedEvent = calls.results.handle_execution_failed.await_args.args[0]
    assert (failed.execution_id, failed.error_type, failed.exit_code, failed.stderr) == (
        "e1",
        ExecutionErrorType.SYSTEM_ERROR,
        -1,
        "Failed to create pod: quota exceeded",
    )
    calls.queue.release.assert_awaited_once_with("e1")
    calls.queue.release_user_slot.assert_awaited_once_with("e1")
    assert calls.k8s.create_pod.await_count == 2


async def test_cancel_stores_the_cancel_before_it_deletes_the_pod(tracer: trace.Tracer) -> None:
    scheduler, calls = _scheduler(tracer, [])
    cancel = ExecutionCancelledEvent(execution_id="e1", cancelled_by="u1", metadata=_METADATA)

    await scheduler.handle_execution_cancelled(cancel)

    assert [name for name, *_ in calls.mock_calls][:5] == [
        "queue.remove",
        "results.handle_execution_cancelled",
        "k8s.delete_pod",
        "queue.release",
        "queue.release_user_slot",
    ]
    calls.k8s.delete_pod.assert_awaited_once_with("e1")


async def test_finish_frees_the_slots_and_starts_the_next_execution(tracer: trace.Tracer) -> None:
    waiting = _requested("e2")
    scheduler, calls = _scheduler(tracer, [waiting])

    await scheduler.finish("e1")

    calls.queue.release.assert_awaited_once_with("e1")
    calls.queue.release_user_slot.assert_awaited_once_with("e1")
    calls.k8s.create_pod.assert_awaited_once_with(waiting)


async def test_a_lost_request_fails_its_execution_and_the_queue_goes_on(tracer: trace.Tracer) -> None:
    fine = _requested("e2")
    scheduler, calls = _scheduler(tracer, [fine])
    calls.queue.try_schedule.side_effect = [QueuedRequestLostError("e1"), ("e2", fine), None]

    await scheduler.schedule_pending()

    calls.results.handle_lost_request.assert_awaited_once_with("e1")
    calls.k8s.create_pod.assert_awaited_once_with(fine)
