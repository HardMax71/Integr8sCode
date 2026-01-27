from __future__ import annotations

import logging
import time
from uuid import uuid4

from app.core.metrics import CoordinatorMetrics, EventMetrics
from app.db.repositories.execution_repository import ExecutionRepository
from app.db.repositories.redis.user_limit_repository import UserLimitRepository
from app.domain.enums.storage import ExecutionErrorType
from app.domain.events.typed import (
    CreatePodCommandEvent,
    ExecutionAcceptedEvent,
    ExecutionCancelledEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionRequestedEvent,
)
from app.events.core import UnifiedProducer


class ExecutionCoordinator:
    """Stateless execution coordinator - fire and forget to k8s.

    Only tracks per-user execution count for rate limiting.
    K8s handles resource allocation and scheduling.
    """

    def __init__(
        self,
        producer: UnifiedProducer,
        execution_repository: ExecutionRepository,
        user_limit_repo: UserLimitRepository,
        logger: logging.Logger,
        coordinator_metrics: CoordinatorMetrics,
        event_metrics: EventMetrics,
    ) -> None:
        self._producer = producer
        self._execution_repository = execution_repository
        self._user_limit = user_limit_repo
        self._logger = logger
        self._metrics = coordinator_metrics
        self._event_metrics = event_metrics

    async def handle_execution_requested(self, event: ExecutionRequestedEvent) -> None:
        """Handle execution request - check limit, fire to k8s."""
        self._logger.info(f"Handling ExecutionRequestedEvent: {event.execution_id}")
        start_time = time.time()
        user_id = event.metadata.user_id

        try:
            if not await self._user_limit.try_increment(user_id):
                await self._publish_limit_exceeded(event)
                self._metrics.record_coordinator_execution_scheduled("limit_exceeded")
                return

            await self._publish_execution_accepted(event)
            await self._publish_create_pod_command(event)

            duration = time.time() - start_time
            self._metrics.record_coordinator_scheduling_duration(duration)
            self._metrics.record_coordinator_execution_scheduled("scheduled")

        except Exception as e:
            await self._user_limit.decrement(user_id)
            self._logger.error(f"Failed to handle execution request {event.execution_id}: {e}", exc_info=True)
            self._metrics.record_coordinator_execution_scheduled("error")

    async def handle_execution_completed(self, event: ExecutionCompletedEvent) -> None:
        """Handle execution completed - decrement user counter."""
        self._logger.info(f"Handling ExecutionCompletedEvent: {event.execution_id}")
        if event.metadata.user_id:
            await self._user_limit.decrement(event.metadata.user_id)

    async def handle_execution_failed(self, event: ExecutionFailedEvent) -> None:
        """Handle execution failed - decrement user counter."""
        self._logger.info(f"Handling ExecutionFailedEvent: {event.execution_id}")
        if event.metadata.user_id:
            await self._user_limit.decrement(event.metadata.user_id)

    async def handle_execution_cancelled(self, event: ExecutionCancelledEvent) -> None:
        """Handle execution cancelled - decrement user counter."""
        self._logger.info(f"Handling ExecutionCancelledEvent: {event.execution_id}")
        exec_rec = await self._execution_repository.get_execution(event.execution_id)
        if exec_rec and exec_rec.user_id:
            await self._user_limit.decrement(exec_rec.user_id)

    async def _publish_create_pod_command(self, request: ExecutionRequestedEvent) -> None:
        """Send CreatePodCommandEvent to k8s-worker."""
        create_pod_cmd = CreatePodCommandEvent(
            saga_id=str(uuid4()),
            execution_id=request.execution_id,
            script=request.script,
            language=request.language,
            language_version=request.language_version,
            runtime_image=request.runtime_image,
            runtime_command=request.runtime_command,
            runtime_filename=request.runtime_filename,
            timeout_seconds=request.timeout_seconds,
            cpu_limit=request.cpu_limit,
            memory_limit=request.memory_limit,
            cpu_request=request.cpu_request,
            memory_request=request.memory_request,
            priority=request.priority,
            metadata=request.metadata,
        )

        await self._producer.produce(event_to_produce=create_pod_cmd, key=request.execution_id)
        self._logger.info(f"Published CreatePodCommandEvent for {request.execution_id}")

    async def _publish_execution_accepted(self, request: ExecutionRequestedEvent) -> None:
        """Publish execution accepted event."""
        event = ExecutionAcceptedEvent(
            execution_id=request.execution_id,
            queue_position=0,
            estimated_wait_seconds=None,
            priority=request.priority,
            metadata=request.metadata,
        )

        await self._producer.produce(event_to_produce=event)

    async def _publish_limit_exceeded(self, request: ExecutionRequestedEvent) -> None:
        """Publish limit exceeded failure event."""
        event = ExecutionFailedEvent(
            execution_id=request.execution_id,
            error_type=ExecutionErrorType.RESOURCE_LIMIT,
            exit_code=-1,
            stderr="User execution limit exceeded",
            resource_usage=None,
            metadata=request.metadata,
            error_message="User execution limit exceeded",
        )

        await self._producer.produce(event_to_produce=event, key=request.execution_id)
