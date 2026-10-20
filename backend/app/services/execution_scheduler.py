import structlog
from opentelemetry import trace

from app.domain.enums import ExecutionErrorType
from app.domain.events import ExecutionCancelledEvent, ExecutionFailedEvent, ExecutionRequestedEvent
from app.services.execution_queue import ExecutionQueueService
from app.services.k8s_worker import KubernetesWorker
from app.services.result_processor import ResultProcessor
from app.services.runtime_settings import RuntimeSettingsLoader


class ExecutionScheduler:
    """Starts queued executions while the concurrency limit has room, and frees an execution's slots when it ends."""

    def __init__(
        self,
        queue: ExecutionQueueService,
        k8s_worker: KubernetesWorker,
        results: ResultProcessor,
        runtime_settings: RuntimeSettingsLoader,
        logger: structlog.stdlib.BoundLogger,
        tracer: trace.Tracer,
    ) -> None:
        self._queue = queue
        self._k8s_worker = k8s_worker
        self._results = results
        self._runtime_settings = runtime_settings
        self.logger = logger
        self._tracer = tracer

    async def handle_execution_requested(self, event: ExecutionRequestedEvent) -> None:
        """Queue a new execution and start it if a slot is free."""
        await self._queue.enqueue(event)
        await self.schedule_pending()

    async def handle_execution_cancelled(self, event: ExecutionCancelledEvent) -> None:
        """Take the execution out of the queue, store it as cancelled, delete its pod and free its slots.

        The cancel is stored before the pod goes, so the deleted pod's failure finds the execution finished.
        """
        execution_id = event.execution_id
        await self._queue.remove(execution_id)
        await self._results.handle_execution_cancelled(event)
        await self._k8s_worker.delete_pod(execution_id)
        await self.finish(execution_id)

    async def finish(self, execution_id: str) -> None:
        """Free an ended execution's slots, then start what the queue holds."""
        await self._queue.release(execution_id)
        await self._queue.release_user_slot(execution_id)
        await self.schedule_pending()

    async def schedule_pending(self) -> None:
        """Start queued executions while slots are free, and report the queue's depth and active slots on the span."""
        with self._tracer.start_as_current_span("queue.schedule_pending") as span:
            settings = await self._runtime_settings.get_effective_settings()
            while (scheduled := await self._queue.try_schedule(settings.max_concurrent_executions)) is not None:
                execution_id, event = scheduled
                try:
                    await self._k8s_worker.create_pod(event)
                except Exception as e:
                    self.logger.error("Failed to create pod", execution_id=execution_id, exc_info=True)
                    await self._results.handle_execution_failed(
                        ExecutionFailedEvent(
                            execution_id=execution_id,
                            aggregate_id=event.aggregate_id,
                            error_type=ExecutionErrorType.SYSTEM_ERROR,
                            exit_code=-1,
                            stderr=f"Failed to create pod: {e}",
                            resource_usage=None,
                            metadata=event.metadata,
                        )
                    )
                    await self._queue.release(execution_id)
                    await self._queue.release_user_slot(execution_id)
            status = await self._queue.get_queue_status()
            span.set_attributes({"queue.depth": status["queue_depth"], "queue.active": status["active_count"]})
