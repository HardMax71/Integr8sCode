import asyncio
import signal
import time
from collections.abc import Coroutine
from typing import Any, TypeAlias
from uuid import uuid4

import redis.asyncio as redis
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.logging import logger
from app.core.metrics.context import get_coordinator_metrics
from app.db.repositories.execution_repository import ExecutionRepository
from app.db.schema.schema_manager import SchemaManager
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.domain.enums.storage import ExecutionErrorType
from app.domain.execution import ResourceUsageDomain
from app.events.core import ConsumerConfig, EventDispatcher, ProducerConfig, UnifiedConsumer, UnifiedProducer
from app.events.event_store import EventStore, create_event_store
from app.events.schema.schema_registry import (
    SchemaRegistryManager,
    create_schema_registry_manager,
    initialize_event_schemas,
)
from app.infrastructure.kafka.events.base import BaseEvent
from app.infrastructure.kafka.events.execution import (
    ExecutionAcceptedEvent,
    ExecutionCancelledEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionRequestedEvent,
)
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.kafka.events.saga import CreatePodCommandEvent
from app.services.coordinator.queue_manager import QueueManager, QueuePriority
from app.services.coordinator.resource_manager import ResourceAllocation, ResourceManager
from app.services.idempotency import IdempotencyManager
from app.services.idempotency.idempotency_manager import IdempotencyConfig, create_idempotency_manager
from app.services.idempotency.middleware import IdempotentConsumerWrapper
from app.services.idempotency.redis_repository import RedisIdempotencyRepository
from app.settings import get_settings

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
            event_store: EventStore,
            execution_repository: ExecutionRepository,
            idempotency_manager: IdempotencyManager,
            consumer_group: str = "execution-coordinator",
            max_concurrent_scheduling: int = 10,
            scheduling_interval_seconds: float = 0.5,
    ):
        self.metrics = get_coordinator_metrics()
        settings = get_settings()

        # Kafka configuration
        self.kafka_servers = settings.KAFKA_BOOTSTRAP_SERVERS
        self.consumer_group = consumer_group

        # Components
        self.queue_manager = QueueManager(
            max_queue_size=10000,
            max_executions_per_user=100,
            stale_timeout_seconds=3600
        )

        self.resource_manager = ResourceManager(
            total_cpu_cores=32.0,
            total_memory_mb=65536,
            total_gpu_count=0
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
        self._running = False
        self._scheduling_task: asyncio.Task | None = None
        self._active_executions: set[str] = set()
        self._execution_resources: ExecutionMap = {}
        self._schema_registry_manager = schema_registry_manager
        self.dispatcher = EventDispatcher()

    async def start(self) -> None:
        """Start the coordinator service"""
        if self._running:
            logger.warning("ExecutionCoordinator already running")
            return

        logger.info("Starting ExecutionCoordinator service...")

        await self.queue_manager.start()

        await self.idempotency_manager.initialize()

        consumer_config = ConsumerConfig(
            bootstrap_servers=self.kafka_servers,
            group_id=self.consumer_group,
            enable_auto_commit=False,
            session_timeout_ms=30000,  # 30 seconds
            heartbeat_interval_ms=10000,  # 10 seconds (must be < session_timeout / 3)
            max_poll_interval_ms=300000,  # 5 minutes - max time between polls
            max_poll_records=100,  # Process max 100 messages at a time for flow control
            fetch_max_wait_ms=500,  # Wait max 500ms for data (reduces latency)
            fetch_min_bytes=1  # Return immediately if any data available
        )

        self.consumer = UnifiedConsumer(
            consumer_config,
            event_dispatcher=self.dispatcher
        )

        # Register handlers with EventDispatcher BEFORE wrapping with idempotency
        @self.dispatcher.register(EventType.EXECUTION_REQUESTED)
        async def handle_requested(event: BaseEvent) -> None:
            await self._route_execution_event(event)

        @self.dispatcher.register(EventType.EXECUTION_COMPLETED)
        async def handle_completed(event: BaseEvent) -> None:
            await self._route_execution_result(event)

        @self.dispatcher.register(EventType.EXECUTION_FAILED)
        async def handle_failed(event: BaseEvent) -> None:
            await self._route_execution_result(event)

        @self.dispatcher.register(EventType.EXECUTION_CANCELLED)
        async def handle_cancelled(event: BaseEvent) -> None:
            await self._route_execution_result(event)

        self.idempotent_consumer = IdempotentConsumerWrapper(
            consumer=self.consumer,
            idempotency_manager=self.idempotency_manager,
            dispatcher=self.dispatcher,
            default_key_strategy="event_based",  # Use event ID for deduplication
            default_ttl_seconds=7200,  # 2 hours TTL for coordinator events
            enable_for_all_handlers=True  # Enable idempotency for ALL handlers
        )

        logger.info("COORDINATOR: Event handlers registered with idempotency protection")

        await self.idempotent_consumer.start([KafkaTopic.EXECUTION_EVENTS])

        # Start scheduling task
        self._running = True
        self._scheduling_task = asyncio.create_task(self._scheduling_loop())

        logger.info("ExecutionCoordinator service started successfully")

    async def stop(self) -> None:
        """Stop the coordinator service"""
        if not self._running:
            return

        logger.info("Stopping ExecutionCoordinator service...")
        self._running = False

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

        await self.queue_manager.stop()

        # Close idempotency manager
        if hasattr(self, 'idempotency_manager') and self.idempotency_manager:
            await self.idempotency_manager.close()

        logger.info(
            f"ExecutionCoordinator service stopped. "
            f"Active executions: {len(self._active_executions)}"
        )

    async def _route_execution_event(self, event: BaseEvent) -> None:
        """Route execution events to appropriate handlers based on event type"""
        logger.info(
            f"COORDINATOR: Routing execution event - type: {event.event_type}, "
            f"id: {event.event_id}, "
            f"actual class: {type(event).__name__}")

        if event.event_type == EventType.EXECUTION_REQUESTED:
            await self._handle_execution_requested(event)  # type: ignore
        elif event.event_type == EventType.EXECUTION_CANCELLED:
            await self._handle_execution_cancelled(event)  # type: ignore
        else:
            logger.debug(f"Ignoring execution event type: {event.event_type}")

    async def _route_execution_result(self, event: BaseEvent) -> None:
        """Route execution result events to appropriate handlers based on event type"""
        if event.event_type == EventType.EXECUTION_COMPLETED:
            await self._handle_execution_completed(event)  # type: ignore
        elif event.event_type == EventType.EXECUTION_FAILED:
            await self._handle_execution_failed(event)  # type: ignore
        else:
            logger.debug(f"Ignoring execution result event type: {event.event_type}")

    async def _handle_execution_requested(
            self,
            event: ExecutionRequestedEvent
    ) -> None:
        """Handle execution requested event - add to queue for processing"""
        logger.info(f"HANDLER CALLED: _handle_execution_requested for event {event.event_id}")
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

            logger.info(
                f"Execution {event.execution_id} added to queue at position {position}"
            )

        except Exception as e:
            logger.error(
                f"Failed to handle execution request {event.execution_id}: {e}",
                exc_info=True
            )
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
            logger.info(f"Execution {execution_id} cancelled and removed from queue")

    async def _handle_execution_completed(self, event: ExecutionCompletedEvent) -> None:
        """Handle execution completed event"""
        execution_id = event.execution_id

        if execution_id in self._execution_resources:
            await self.resource_manager.release_allocation(execution_id)
            del self._execution_resources[execution_id]

        # Remove from active set
        self._active_executions.discard(execution_id)
        self.metrics.update_coordinator_active_executions(len(self._active_executions))

        logger.info(f"Execution {execution_id} completed, resources released")

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
        while self._running:
            try:
                # Get next execution from queue
                execution = await self.queue_manager.get_next_execution()

                if execution:
                    # Schedule execution
                    asyncio.create_task(self._schedule_execution(execution))
                else:
                    # No executions in queue, wait
                    await asyncio.sleep(self.scheduling_interval)

            except Exception as e:
                logger.error(f"Error in scheduling loop: {e}", exc_info=True)
                await asyncio.sleep(5)  # Wait before retrying

    async def _schedule_execution(self, event: ExecutionRequestedEvent) -> None:
        """Schedule a single execution"""
        async with self._scheduling_semaphore:
            start_time = time.time()

            try:
                # Check if already active (shouldn't happen, but be safe)
                if event.execution_id in self._active_executions:
                    logger.warning(
                        f"Execution {event.execution_id} already active, skipping"
                    )
                    return

                # Request resource allocation
                allocation = await self.resource_manager.request_allocation(
                    event.execution_id,
                    event.language,
                    requested_cpu=None,  # Use defaults for now
                    requested_memory_mb=None,
                    requested_gpu=0
                )

                if not allocation:
                    # No resources available, requeue
                    await self.queue_manager.requeue_execution(
                        event,
                        increment_retry=False
                    )
                    logger.info(
                        f"No resources available for {event.execution_id}, requeued"
                    )
                    return

                # Track allocation
                self._execution_resources[event.execution_id] = allocation
                self._active_executions.add(event.execution_id)
                self.metrics.update_coordinator_active_executions(len(self._active_executions))

                # Publish execution started event for workers
                logger.info(f"About to publish ExecutionStartedEvent for {event.execution_id}")
                try:
                    await self._publish_execution_started(event)
                    logger.info(f"Successfully published ExecutionStartedEvent for {event.execution_id}")
                except Exception as publish_error:
                    logger.error(f"Failed to publish ExecutionStartedEvent for {event.execution_id}: {publish_error}",
                                 exc_info=True)
                    raise

                # Track metrics
                queue_time = start_time - event.timestamp.timestamp()
                priority = getattr(event, 'priority', QueuePriority.NORMAL.value)
                self.metrics.record_coordinator_queue_time(queue_time, QueuePriority(priority).name)

                scheduling_duration = time.time() - start_time
                self.metrics.record_coordinator_scheduling_duration(scheduling_duration)
                self.metrics.record_coordinator_execution_scheduled("scheduled")

                logger.info(
                    f"Scheduled execution {event.execution_id}. "
                    f"Queue time: {queue_time:.2f}s, "
                    f"Resources: {allocation.cpu_cores} CPU, "
                    f"{allocation.memory_mb}MB RAM"
                )

            except Exception as e:
                logger.error(
                    f"Failed to schedule execution {event.execution_id}: {e}",
                    exc_info=True
                )

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
        # Prefer execution record user_id to avoid missing attribution
        exec_rec = await self.execution_repository.get_execution(request.execution_id)
        user_id: str = exec_rec.user_id if exec_rec and exec_rec.user_id else "system"

        return EventMetadata(
            service_name="execution-coordinator",
            service_version="1.0.0",
            user_id=user_id,
            correlation_id=request.metadata.correlation_id,
        )

    async def _publish_execution_started(
            self,
            request: ExecutionRequestedEvent
    ) -> None:
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

        await self.producer.produce(
            event_to_produce=create_pod_cmd,
            key=request.execution_id
        )

    async def _publish_execution_accepted(
            self,
            request: ExecutionRequestedEvent,
            position: int,
            priority: int
    ) -> None:
        """Publish execution accepted event to notify that request was valid and queued"""
        logger.info(f"Publishing ExecutionAcceptedEvent for execution {request.execution_id}")

        event = ExecutionAcceptedEvent(
            execution_id=request.execution_id,
            queue_position=position,
            estimated_wait_seconds=None,  # Could calculate based on queue analysis
            priority=priority,
            metadata=request.metadata
        )

        await self.producer.produce(event_to_produce=event)
        logger.info(f"ExecutionAcceptedEvent published for {request.execution_id}")

    async def _publish_queue_full(
            self,
            request: ExecutionRequestedEvent,
            error: str
    ) -> None:
        """Publish queue full event"""
        # Get queue stats for context
        queue_stats = await self.queue_manager.get_queue_stats()

        event = ExecutionFailedEvent(
            execution_id=request.execution_id,
            error_type=ExecutionErrorType.RESOURCE_LIMIT,
            exit_code=-1,
            stderr=f"Queue full: {error}. Queue size: {queue_stats.get('total_size', 'unknown')}",
            resource_usage=ResourceUsageDomain.from_dict({}),
            metadata=request.metadata,
            error_message=error,
        )

        await self.producer.produce(event_to_produce=event,
                                    key=request.execution_id)

    async def _publish_scheduling_failed(
            self,
            request: ExecutionRequestedEvent,
            error: str
    ) -> None:
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
            resource_usage=ResourceUsageDomain.from_dict({}),
            metadata=request.metadata,
            error_message=error
        )

        await self.producer.produce(event_to_produce=event,
                                    key=request.execution_id)

    async def get_status(self) -> dict[str, Any]:
        """Get coordinator status"""
        return {
            "running": self._running,
            "active_executions": len(self._active_executions),
            "queue_stats": await self.queue_manager.get_queue_stats(),
            "resource_stats": await self.resource_manager.get_resource_stats()
        }


async def run_coordinator() -> None:
    """Run the execution coordinator service"""
    # Initialize schema registry
    logger.info("Initializing schema registry for coordinator...")
    schema_registry_manager = create_schema_registry_manager()
    await initialize_event_schemas(schema_registry_manager)

    # Initialize producer
    logger.info("Initializing Kafka producer for coordinator...")
    settings = get_settings()
    config = ProducerConfig(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS
    )
    producer = UnifiedProducer(config, schema_registry_manager)
    await producer.start()

    # Initialize database and event store
    settings = get_settings()
    db_client: AsyncIOMotorClient = AsyncIOMotorClient(
        settings.MONGODB_URL,
        tz_aware=True,
        serverSelectionTimeoutMS=5000
    )
    db_name = settings.PROJECT_NAME + "_test" if settings.TESTING else settings.PROJECT_NAME
    database = db_client[db_name]

    # Ensure DB schema (indexes/validators)
    await SchemaManager(database).apply_all()

    # Initialize event store (schema ensured separately)
    logger.info("Creating event store for coordinator...")
    event_store = create_event_store(
        db=database,
        schema_registry=schema_registry_manager,
        ttl_days=90
    )

    # Build repositories and idempotency manager
    exec_repo = ExecutionRepository(database)
    r = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        password=settings.REDIS_PASSWORD,
        ssl=settings.REDIS_SSL,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        decode_responses=settings.REDIS_DECODE_RESPONSES,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    idem_repo = RedisIdempotencyRepository(r, key_prefix="idempotency")
    idem_manager = create_idempotency_manager(repository=idem_repo, config=IdempotencyConfig())
    await idem_manager.initialize()

    coordinator = ExecutionCoordinator(
        producer=producer,
        schema_registry_manager=schema_registry_manager,
        event_store=event_store,
        execution_repository=exec_repo,
        idempotency_manager=idem_manager,
    )

    # Setup signal handlers
    def signal_handler(sig: int, frame: Any) -> None:
        logger.info(f"Received signal {sig}, initiating shutdown...")
        asyncio.create_task(coordinator.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await coordinator.start()

        # Keep running until stopped
        while coordinator._running:
            await asyncio.sleep(60)

            # Log status periodically
            status = await coordinator.get_status()
            logger.info(f"Coordinator status: {status}")

    except Exception as e:
        logger.error(f"Coordinator error: {e}", exc_info=True)
    finally:
        await coordinator.stop()
        await producer.stop()
        db_client.close()


if __name__ == "__main__":
    # Run coordinator as standalone service

    settings = get_settings()
    asyncio.run(run_coordinator())
