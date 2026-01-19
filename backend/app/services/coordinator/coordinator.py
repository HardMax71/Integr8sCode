import asyncio
import logging
import time
from collections.abc import Coroutine
from typing import Any, TypeAlias
from uuid import uuid4

from app.core.metrics import CoordinatorMetrics, EventMetrics
from app.db.repositories.execution_repository import ExecutionRepository
from app.domain.enums.events import EventType
from app.domain.enums.kafka import CONSUMER_GROUP_SUBSCRIPTIONS, GroupId
from app.domain.enums.storage import ExecutionErrorType
from app.domain.events.typed import (
    CreatePodCommandEvent,
    EventMetadata,
    ExecutionAcceptedEvent,
    ExecutionCancelledEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionRequestedEvent,
)
from app.events.core import ConsumerConfig, EventDispatcher, UnifiedConsumer, UnifiedProducer
from app.events.event_store import EventStore
from app.events.schema.schema_registry import (
    SchemaRegistryManager,
)
from app.services.coordinator.queue_manager import QueueManager, QueuePriority
from app.services.coordinator.resource_manager import ResourceAllocation, ResourceManager
from app.services.idempotency import IdempotencyManager
from app.services.idempotency.middleware import IdempotentConsumerWrapper
from app.settings import Settings

EventHandler: TypeAlias = Coroutine[Any, Any, None]
ExecutionMap: TypeAlias = dict[str, ResourceAllocation]


class ExecutionCoordinator:
    """
    Coordinates execution scheduling across the system.

    This service:
    1. Consumes ExecutionRequested events
    2. Manages execution queue with priority
    3. Enforces rate limits
    4. Allocates resources
    5. Publishes ExecutionStarted events for workers
    """

    def __init__(
        self,
        producer: UnifiedProducer,
        schema_registry_manager: SchemaRegistryManager,
        settings: Settings,
        event_store: EventStore,
        execution_repository: ExecutionRepository,
        idempotency_manager: IdempotencyManager,
        logger: logging.Logger,
        coordinator_metrics: CoordinatorMetrics,
        event_metrics: EventMetrics,
        consumer_group: str = GroupId.EXECUTION_COORDINATOR,
        max_concurrent_scheduling: int = 10,
        scheduling_interval_seconds: float = 0.5,
    ):
        self.logger = logger
        self.metrics = coordinator_metrics
        self._event_metrics = event_metrics
        self._settings = settings

        # Kafka configuration
        self.kafka_servers = self._settings.KAFKA_BOOTSTRAP_SERVERS
        self.consumer_group = consumer_group

        # Components
        self.queue_manager = QueueManager(
            logger=self.logger,
            coordinator_metrics=coordinator_metrics,
            max_queue_size=10000,
            max_executions_per_user=100,
            stale_timeout_seconds=3600,
        )

        self.resource_manager = ResourceManager(
            logger=self.logger,
            coordinator_metrics=coordinator_metrics,
            total_cpu_cores=32.0,
            total_memory_mb=65536,
            total_gpu_count=0,
        )

        # Kafka components
        self.consumer: UnifiedConsumer | None = None
        self.idempotent_consumer: IdempotentConsumerWrapper | None = None
        self.producer: UnifiedProducer = producer

        # Persistence via repositories
        self.execution_repository = execution_repository
        self.idempotency_manager = idempotency_manager
        self._event_store = event_store

        # Scheduling
        self.max_concurrent_scheduling = max_concurrent_scheduling
        self.scheduling_interval = scheduling_interval_seconds
        self._scheduling_semaphore = asyncio.Semaphore(max_concurrent_scheduling)

        # State tracking
        self._scheduling_task: asyncio.Task[None] | None = None
        self._active_executions: set[str] = set()
        self._execution_resources: ExecutionMap = {}
        self._schema_registry_manager = schema_registry_manager
        self.dispatcher = EventDispatcher(logger=self.logger)

    async def __aenter__(self) -> "ExecutionCoordinator":
        """Start the coordinator service."""
        self.logger.info("Starting ExecutionCoordinator service...")

        self.logger.info("Queue manager initialized")

        await self.idempotency_manager.initialize()

        consumer_config = ConsumerConfig(
            bootstrap_servers=self.kafka_servers,
            group_id=f"{self.consumer_group}.{self._settings.KAFKA_GROUP_SUFFIX}",
            enable_auto_commit=False,
            session_timeout_ms=self._settings.KAFKA_SESSION_TIMEOUT_MS,
            heartbeat_interval_ms=self._settings.KAFKA_HEARTBEAT_INTERVAL_MS,
            max_poll_interval_ms=self._settings.KAFKA_MAX_POLL_INTERVAL_MS,
            request_timeout_ms=self._settings.KAFKA_REQUEST_TIMEOUT_MS,
            max_poll_records=100,  # Process max 100 messages at a time for flow control
            fetch_max_wait_ms=500,  # Wait max 500ms for data (reduces latency)
            fetch_min_bytes=1,  # Return immediately if any data available
        )

        self.consumer = UnifiedConsumer(
            consumer_config,
            event_dispatcher=self.dispatcher,
            schema_registry=self._schema_registry_manager,
            settings=self._settings,
            logger=self.logger,
            event_metrics=self._event_metrics,
        )

        # Register handlers with EventDispatcher BEFORE wrapping with idempotency
        @self.dispatcher.register(EventType.EXECUTION_REQUESTED)
        async def handle_requested(event: ExecutionRequestedEvent) -> None:
            await self._route_execution_event(event)

        @self.dispatcher.register(EventType.EXECUTION_COMPLETED)
        async def handle_completed(event: ExecutionCompletedEvent) -> None:
            await self._route_execution_result(event)

        @self.dispatcher.register(EventType.EXECUTION_FAILED)
        async def handle_failed(event: ExecutionFailedEvent) -> None:
            await self._route_execution_result(event)

        @self.dispatcher.register(EventType.EXECUTION_CANCELLED)
        async def handle_cancelled(event: ExecutionCancelledEvent) -> None:
            await self._route_execution_event(event)

        self.idempotent_consumer = IdempotentConsumerWrapper(
            consumer=self.consumer,
            idempotency_manager=self.idempotency_manager,
            dispatcher=self.dispatcher,
            logger=self.logger,
            default_key_strategy="event_based",  # Use event ID for deduplication
            default_ttl_seconds=7200,  # 2 hours TTL for coordinator events
            enable_for_all_handlers=True,  # Enable idempotency for ALL handlers
        )

        self.logger.info("COORDINATOR: Event handlers registered with idempotency protection")

        await self.idempotent_consumer.start(list(CONSUMER_GROUP_SUBSCRIPTIONS[GroupId.EXECUTION_COORDINATOR]))

        # Start scheduling task
        self._scheduling_task = asyncio.create_task(self._scheduling_loop())

        self.logger.info("ExecutionCoordinator service started successfully")
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Stop the coordinator service."""
        self.logger.info("Stopping ExecutionCoordinator service...")

        # Stop scheduling task
        if self._scheduling_task:
            self._scheduling_task.cancel()
            try:
                await self._scheduling_task
            except asyncio.CancelledError:
                pass

        # Stop consumer (idempotent wrapper only)
        if self.idempotent_consumer:
            await self.idempotent_consumer.stop()

        # Close idempotency manager
        if hasattr(self, "idempotency_manager") and self.idempotency_manager:
            await self.idempotency_manager.close()

        self.logger.info(f"ExecutionCoordinator service stopped. Active executions: {len(self._active_executions)}")

    async def _route_execution_event(self, event: ExecutionRequestedEvent | ExecutionCancelledEvent) -> None:
        """Route execution events to appropriate handlers based on event type"""
        self.logger.info(
            f"COORDINATOR: Routing execution event - type: {event.event_type}, "
            f"id: {event.event_id}, "
            f"actual class: {type(event).__name__}"
        )

        if event.event_type == EventType.EXECUTION_REQUESTED:
            await self._handle_execution_requested(event)
        elif event.event_type == EventType.EXECUTION_CANCELLED:
            await self._handle_execution_cancelled(event)
        else:
            self.logger.debug(f"Ignoring execution event type: {event.event_type}")

    async def _route_execution_result(self, event: ExecutionCompletedEvent | ExecutionFailedEvent) -> None:
        """Route execution result events to appropriate handlers based on event type"""
        if event.event_type == EventType.EXECUTION_COMPLETED:
            await self._handle_execution_completed(event)
        elif event.event_type == EventType.EXECUTION_FAILED:
            await self._handle_execution_failed(event)
        else:
            self.logger.debug(f"Ignoring execution result event type: {event.event_type}")

    async def _handle_execution_requested(self, event: ExecutionRequestedEvent) -> None:
        """Handle execution requested event - add to queue for processing"""
        self.logger.info(f"HANDLER CALLED: _handle_execution_requested for event {event.event_id}")
        start_time = time.time()

        try:
            # Add to queue with priority
            success, position, error = await self.queue_manager.add_execution(
                event,
                priority=QueuePriority(event.priority),
            )

            if not success:
                # Publish queue full event
                await self._publish_queue_full(event, error or "Queue is full")
                self.metrics.record_coordinator_execution_scheduled("queue_full")
                return

            # Publish ExecutionAcceptedEvent
            if position is None:
                position = 0
            await self._publish_execution_accepted(event, position, event.priority)

            # Track metrics
            duration = time.time() - start_time
            self.metrics.record_coordinator_scheduling_duration(duration)
            self.metrics.record_coordinator_execution_scheduled("queued")

            self.logger.info(f"Execution {event.execution_id} added to queue at position {position}")

            # Schedule immediately if at front of queue (position 0)
            if position == 0:
                await self._schedule_execution(event)

        except Exception as e:
            self.logger.error(f"Failed to handle execution request {event.execution_id}: {e}", exc_info=True)
            self.metrics.record_coordinator_execution_scheduled("error")

    async def _handle_execution_cancelled(self, event: ExecutionCancelledEvent) -> None:
        """Handle execution cancelled event"""
        execution_id = event.execution_id

        removed = await self.queue_manager.remove_execution(execution_id)

        if execution_id in self._execution_resources:
            await self.resource_manager.release_allocation(execution_id)
            del self._execution_resources[execution_id]

        self._active_executions.discard(execution_id)
        self.metrics.update_coordinator_active_executions(len(self._active_executions))

        if removed:
            self.logger.info(f"Execution {execution_id} cancelled and removed from queue")

    async def _handle_execution_completed(self, event: ExecutionCompletedEvent) -> None:
        """Handle execution completed event"""
        execution_id = event.execution_id

        if execution_id in self._execution_resources:
            await self.resource_manager.release_allocation(execution_id)
            del self._execution_resources[execution_id]

        # Remove from active set
        self._active_executions.discard(execution_id)
        self.metrics.update_coordinator_active_executions(len(self._active_executions))

        self.logger.info(f"Execution {execution_id} completed, resources released")

    async def _handle_execution_failed(self, event: ExecutionFailedEvent) -> None:
        """Handle execution failed event"""
        execution_id = event.execution_id

        # Release resources
        if execution_id in self._execution_resources:
            await self.resource_manager.release_allocation(execution_id)
            del self._execution_resources[execution_id]

        # Remove from active set
        self._active_executions.discard(execution_id)
        self.metrics.update_coordinator_active_executions(len(self._active_executions))

    async def _scheduling_loop(self) -> None:
        """Main scheduling loop"""
        try:
            while True:
                try:
                    # Get next execution from queue
                    execution = await self.queue_manager.get_next_execution()

                    if execution:
                        # Schedule execution
                        asyncio.create_task(self._schedule_execution(execution))
                    else:
                        # No executions in queue, wait
                        await asyncio.sleep(self.scheduling_interval)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.logger.error(f"Error in scheduling loop: {e}", exc_info=True)
                    await asyncio.sleep(5)  # Wait before retrying
        except asyncio.CancelledError:
            self.logger.info("Scheduling loop cancelled")

    async def _schedule_execution(self, event: ExecutionRequestedEvent) -> None:
        """Schedule a single execution"""
        async with self._scheduling_semaphore:
            start_time = time.time()
            execution_id = event.execution_id

            # Atomic check-and-claim: no await between check and add prevents TOCTOU race
            # when both eager scheduling (position=0) and _scheduling_loop try to schedule
            if execution_id in self._active_executions:
                self.logger.debug(f"Execution {execution_id} already claimed, skipping")
                return
            self._active_executions.add(execution_id)

            try:
                # Request resource allocation
                allocation = await self.resource_manager.request_allocation(
                    execution_id,
                    event.language,
                    requested_cpu=None,  # Use defaults for now
                    requested_memory_mb=None,
                    requested_gpu=0,
                )

                if not allocation:
                    # No resources available, release claim and requeue
                    self._active_executions.discard(execution_id)
                    await self.queue_manager.requeue_execution(event, increment_retry=False)
                    self.logger.info(f"No resources available for {execution_id}, requeued")
                    return

                # Track allocation (already in _active_executions from claim above)
                self._execution_resources[execution_id] = allocation
                self.metrics.update_coordinator_active_executions(len(self._active_executions))

                # Publish execution started event for workers
                self.logger.info(f"About to publish ExecutionStartedEvent for {event.execution_id}")
                try:
                    await self._publish_execution_started(event)
                    self.logger.info(f"Successfully published ExecutionStartedEvent for {event.execution_id}")
                except Exception as publish_error:
                    self.logger.error(
                        f"Failed to publish ExecutionStartedEvent for {event.execution_id}: {publish_error}",
                        exc_info=True,
                    )
                    raise

                # Track metrics
                queue_time = start_time - event.timestamp.timestamp()
                priority = getattr(event, "priority", QueuePriority.NORMAL.value)
                self.metrics.record_coordinator_queue_time(queue_time, QueuePriority(priority).name)

                scheduling_duration = time.time() - start_time
                self.metrics.record_coordinator_scheduling_duration(scheduling_duration)
                self.metrics.record_coordinator_execution_scheduled("scheduled")

                self.logger.info(
                    f"Scheduled execution {event.execution_id}. "
                    f"Queue time: {queue_time:.2f}s, "
                    f"Resources: {allocation.cpu_cores} CPU, "
                    f"{allocation.memory_mb}MB RAM"
                )

            except Exception as e:
                self.logger.error(f"Failed to schedule execution {event.execution_id}: {e}", exc_info=True)

                # Release any allocated resources
                if event.execution_id in self._execution_resources:
                    await self.resource_manager.release_allocation(event.execution_id)
                    del self._execution_resources[event.execution_id]

                self._active_executions.discard(event.execution_id)
                self.metrics.update_coordinator_active_executions(len(self._active_executions))
                self.metrics.record_coordinator_execution_scheduled("error")

                # Publish failure event
                await self._publish_scheduling_failed(event, str(e))

    async def _build_command_metadata(self, request: ExecutionRequestedEvent) -> EventMetadata:
        """Build metadata for CreatePodCommandEvent with guaranteed user_id."""
        # Prefer execution record user_id to avoid missing attribution
        exec_rec = await self.execution_repository.get_execution(request.execution_id)
        user_id: str = exec_rec.user_id if exec_rec and exec_rec.user_id else "system"

        return EventMetadata(
            service_name="execution-coordinator",
            service_version="1.0.0",
            user_id=user_id,
            correlation_id=request.metadata.correlation_id,
        )

    async def _publish_execution_started(self, request: ExecutionRequestedEvent) -> None:
        """Send CreatePodCommandEvent to k8s-worker via SAGA_COMMANDS topic"""
        metadata = await self._build_command_metadata(request)

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
            metadata=metadata,
        )

        await self.producer.produce(event_to_produce=create_pod_cmd, key=request.execution_id)

    async def _publish_execution_accepted(self, request: ExecutionRequestedEvent, position: int, priority: int) -> None:
        """Publish execution accepted event to notify that request was valid and queued"""
        self.logger.info(f"Publishing ExecutionAcceptedEvent for execution {request.execution_id}")

        event = ExecutionAcceptedEvent(
            execution_id=request.execution_id,
            queue_position=position,
            estimated_wait_seconds=None,  # Could calculate based on queue analysis
            priority=priority,
            metadata=request.metadata,
        )

        await self.producer.produce(event_to_produce=event)
        self.logger.info(f"ExecutionAcceptedEvent published for {request.execution_id}")

    async def _publish_queue_full(self, request: ExecutionRequestedEvent, error: str) -> None:
        """Publish queue full event"""
        # Get queue stats for context
        queue_stats = await self.queue_manager.get_queue_stats()

        event = ExecutionFailedEvent(
            execution_id=request.execution_id,
            error_type=ExecutionErrorType.RESOURCE_LIMIT,
            exit_code=-1,
            stderr=f"Queue full: {error}. Queue size: {queue_stats.get('total_size', 'unknown')}",
            resource_usage=None,
            metadata=request.metadata,
            error_message=error,
        )

        await self.producer.produce(event_to_produce=event, key=request.execution_id)

    async def _publish_scheduling_failed(self, request: ExecutionRequestedEvent, error: str) -> None:
        """Publish scheduling failed event"""
        # Get resource stats for context
        resource_stats = await self.resource_manager.get_resource_stats()

        event = ExecutionFailedEvent(
            execution_id=request.execution_id,
            error_type=ExecutionErrorType.SYSTEM_ERROR,
            exit_code=-1,
            stderr=f"Failed to schedule execution: {error}. "
            f"Available resources: CPU={resource_stats.available.cpu_cores}, "
            f"Memory={resource_stats.available.memory_mb}MB",
            resource_usage=None,
            metadata=request.metadata,
            error_message=error,
        )

        await self.producer.produce(event_to_produce=event, key=request.execution_id)

    async def get_status(self) -> dict[str, Any]:
        """Get coordinator status"""
        return {
            "scheduling_task_active": self._scheduling_task is not None and not self._scheduling_task.done(),
            "active_executions": len(self._active_executions),
            "queue_stats": await self.queue_manager.get_queue_stats(),
            "resource_stats": await self.resource_manager.get_resource_stats(),
        }
