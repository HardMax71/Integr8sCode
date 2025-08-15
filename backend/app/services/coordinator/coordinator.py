"""
Execution coordinator service for managing execution scheduling.

This service coordinates execution requests, manages queues, enforces rate limits,
and allocates resources using modern Python 3.11+ features.
"""

import asyncio
import signal
import time

# Type aliases
from collections.abc import Coroutine
from typing import Any, TypeAlias

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings
from app.core.logging import logger
from app.core.metrics import Counter, Gauge, Histogram
from app.events.core.consumer import ConsumerConfig, UnifiedConsumer
from app.events.core.producer import UnifiedProducer, create_unified_producer
from app.events.schema.schema_registry import (
    SchemaRegistryManager,
    create_schema_registry_manager,
    initialize_event_schemas,
)
from app.events.store.event_store import EventStore, create_event_store
from app.schemas_avro.event_schemas import (
    BaseEvent,
    EventType,
    ExecutionErrorType,
    ExecutionFailedEvent,
    ExecutionRequestedEvent,
    get_topic_for_event,
)
from app.services.coordinator.queue_manager import QueueManager, QueuePriority
from app.services.coordinator.rate_limiter import RateLimitConfig, RateLimiter
from app.services.coordinator.resource_manager import ResourceAllocation, ResourceManager
from app.services.idempotency import create_idempotency_manager
from app.services.idempotency.middleware import IdempotentConsumerWrapper

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
            kafka_bootstrap_servers: str | None = None,
            consumer_group: str = "execution-coordinator",
            max_concurrent_scheduling: int = 10,
            scheduling_interval_seconds: float = 0.5,
            producer: UnifiedProducer | None = None,
            schema_registry_manager: SchemaRegistryManager | None = None,
            event_store: EventStore | None = None,
    ):
        settings = get_settings()

        # Kafka configuration
        self.kafka_servers = kafka_bootstrap_servers or settings.KAFKA_BOOTSTRAP_SERVERS
        self.consumer_group = consumer_group

        # Components
        self.queue_manager = QueueManager(
            max_queue_size=10000,
            max_executions_per_user=100,
            stale_timeout_seconds=3600
        )

        self.rate_limiter = RateLimiter(
            RateLimitConfig(
                requests_per_minute=100,
                requests_per_hour=2000,
                requests_per_day=20000,
                user_requests_per_minute=20,
                user_requests_per_hour=200,
                user_requests_per_day=1000
            )
        )

        self.resource_manager = ResourceManager(
            total_cpu_cores=32.0,
            total_memory_mb=65536,
            total_gpu_count=0
        )

        # Kafka components
        self.consumer: UnifiedConsumer | None = None
        self.idempotent_consumer: IdempotentConsumerWrapper | None = None
        self.producer: UnifiedProducer | None = producer
        self._producer_provided = producer is not None

        # Database
        self.db_client: AsyncIOMotorClient | None = None
        self.database: AsyncIOMotorDatabase | None = None
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

        # Metrics
        self.executions_scheduled = Counter(
            "coordinator_executions_scheduled_total",
            "Total executions scheduled",
            ["status"]
        )
        self.scheduling_duration = Histogram(
            "coordinator_scheduling_duration_seconds",
            "Time taken to schedule execution",
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0]
        )
        self.active_executions_gauge = Gauge(
            "coordinator_active_executions",
            "Number of active executions being coordinated"
        )
        self.queue_time = Histogram(
            "coordinator_queue_time_seconds",
            "Time spent in coordinator queue",
            ["priority"],
            buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0]
        )

    async def start(self) -> None:
        """Start the coordinator service"""
        if self._running:
            logger.warning("ExecutionCoordinator already running")
            return

        logger.info("Starting ExecutionCoordinator service...")

        # Start components
        await self.queue_manager.start()

        # Initialize database connection
        settings = get_settings()
        self.db_client = AsyncIOMotorClient(
            settings.MONGODB_URL,
            tz_aware=True,
            serverSelectionTimeoutMS=5000
        )
        db_name = settings.PROJECT_NAME + "_test" if settings.TESTING else settings.PROJECT_NAME
        self.database = self.db_client[db_name]

        # Verify connection
        await self.db_client.admin.command("ping")
        logger.info(f"Connected to database: {db_name}")

        # Initialize idempotency manager
        self.idempotency_manager = create_idempotency_manager(self.database)
        await self.idempotency_manager.initialize()

        # Create producer if not provided
        if not self.producer:
            self.producer = create_unified_producer()
            await self.producer.start()

        # Create consumer
        config = ConsumerConfig(
            bootstrap_servers=self.kafka_servers,
            group_id=self.consumer_group,
            topics=[get_topic_for_event(EventType.EXECUTION_REQUESTED).value,
                    get_topic_for_event(EventType.EXECUTION_COMPLETED).value,
                    get_topic_for_event(EventType.EXECUTION_FAILED).value,
                    get_topic_for_event(EventType.EXECUTION_CANCELLED).value],
            enable_auto_commit=False,
            session_timeout_ms=30000,  # 30 seconds
            heartbeat_interval_ms=10000,  # 10 seconds (must be < session_timeout / 3)
            max_poll_interval_ms=300000  # 5 minutes
        )

        self.consumer = UnifiedConsumer(config, self._schema_registry_manager)

        # Create idempotent consumer wrapper
        self.idempotent_consumer = IdempotentConsumerWrapper(
            consumer=self.consumer,
            idempotency_manager=self.idempotency_manager,
            default_key_strategy="event_based",
            default_ttl_seconds=3600,
            enable_for_all_handlers=False  # We'll register handlers individually
        )

        # Subscribe idempotent handlers
        logger.info(
            f"COORDINATOR: Subscribing idempotent handler for event type: {EventType.EXECUTION_REQUESTED.value}")
        self.idempotent_consumer.subscribe_idempotent_handler(
            EventType.EXECUTION_REQUESTED,
            self._handle_execution_requested,
            key_strategy="event_based",
            cache_result=False  # Don't cache result for request events
        )
        logger.info("COORDINATOR: Idempotent handler subscribed")

        # Subscribe to completion/failure events for resource cleanup (with idempotency)
        self.idempotent_consumer.subscribe_idempotent_handler(
            EventType.EXECUTION_COMPLETED,
            self._handle_execution_completed,
            key_strategy="event_based",
            cache_result=False
        )
        self.idempotent_consumer.subscribe_idempotent_handler(
            EventType.EXECUTION_FAILED,
            self._handle_execution_failed,
            key_strategy="event_based",
            cache_result=False
        )
        self.idempotent_consumer.subscribe_idempotent_handler(
            EventType.EXECUTION_CANCELLED,
            self._handle_execution_cancelled,
            key_strategy="event_based",
            cache_result=False
        )

        # Start consumer with idempotency
        await self.idempotent_consumer.start()

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

        # Stop components
        if self.idempotent_consumer:
            await self.idempotent_consumer.stop()
        elif self.consumer:
            await self.consumer.stop()

        await self.queue_manager.stop()

        # Close idempotency manager
        if hasattr(self, 'idempotency_manager') and self.idempotency_manager:
            await self.idempotency_manager.close()
        
        # Stop producer if we created it
        if self.producer and not self._producer_provided:
            await self.producer.stop()
        
        # Close database connection
        if self.db_client:
            self.db_client.close()

        logger.info(
            f"ExecutionCoordinator service stopped. "
            f"Active executions: {len(self._active_executions)}"
        )

    async def _handle_execution_requested(
            self,
            event: ExecutionRequestedEvent,
            record: Any
    ) -> None:
        """Handle execution requested event"""
        logger.info(f"HANDLER CALLED: _handle_execution_requested for event {event.event_id}")
        start_time = time.time()

        try:
            user_id = event.metadata.user_id

            # Check rate limit
            allowed, wait_time, limit_type = await self.rate_limiter.check_rate_limit(
                user_id=user_id
            )

            if not allowed:
                # Publish rate limit exceeded event
                await self._publish_rate_limit_exceeded(
                    event,
                    wait_time or 0.0,
                    limit_type or "unknown"
                )
                self.executions_scheduled.labels(status="rate_limited").inc()
                return

            # Add to queue with priority - need to add priority field to ExecutionRequestedEvent
            priority = getattr(event, 'priority', QueuePriority.NORMAL.value)
            success, position, error = await self.queue_manager.add_execution(
                event,
                priority=QueuePriority(priority)
            )

            if not success:
                # Publish queue full event
                await self._publish_queue_full(event, error or "Queue is full")
                self.executions_scheduled.labels(status="queue_full").inc()
                return

            # Track metrics
            duration = time.time() - start_time
            self.scheduling_duration.observe(duration)
            self.executions_scheduled.labels(status="queued").inc()

            logger.info(
                f"Execution {event.execution_id} added to queue at position {position}"
            )

        except Exception as e:
            logger.error(
                f"Failed to handle execution request {event.execution_id}: {e}",
                exc_info=True
            )
            self.executions_scheduled.labels(status="error").inc()

    async def _handle_execution_cancelled(self, event: BaseEvent, record: Any) -> None:
        """Handle execution cancelled event"""
        execution_id = getattr(event, "execution_id", None)
        if not execution_id:
            return

        # Remove from queue
        removed = await self.queue_manager.remove_execution(execution_id)

        # Release resources if allocated
        if execution_id in self._execution_resources:
            await self.resource_manager.release_allocation(execution_id)
            del self._execution_resources[execution_id]

        # Remove from active set
        self._active_executions.discard(execution_id)
        self.active_executions_gauge.set(len(self._active_executions))

        if removed:
            logger.info(f"Execution {execution_id} cancelled and removed from queue")

    async def _handle_execution_completed(self, event: BaseEvent, record: Any) -> None:
        """Handle execution completed event"""
        execution_id = getattr(event, "execution_id", None)
        if not execution_id:
            return

        # Release resources
        if execution_id in self._execution_resources:
            await self.resource_manager.release_allocation(execution_id)
            del self._execution_resources[execution_id]

        # Remove from active set
        self._active_executions.discard(execution_id)
        self.active_executions_gauge.set(len(self._active_executions))

        logger.info(f"Execution {execution_id} completed, resources released")

    async def _handle_execution_failed(self, event: ExecutionFailedEvent, record: Any) -> None:
        """Handle execution failed event"""
        execution_id = event.execution_id

        # Release resources
        if execution_id in self._execution_resources:
            await self.resource_manager.release_allocation(execution_id)
            del self._execution_resources[execution_id]

        # Remove from active set
        self._active_executions.discard(execution_id)
        self.active_executions_gauge.set(len(self._active_executions))

        # Check if recoverable and should be requeued
        recoverable = getattr(event, 'recoverable', False)
        if recoverable and execution_id not in self._active_executions:
            # Get original event from event store if available
            if self._event_store:
                events = await self._event_store.get_execution_events(
                    execution_id,
                    [EventType.EXECUTION_REQUESTED]
                )
                if events:
                    original_event = events[0]
                    if isinstance(original_event, ExecutionRequestedEvent):
                        # Requeue with lower priority
                        await self.queue_manager.requeue_execution(
                            original_event,
                            increment_retry=True
                        )
                        logger.info(
                            f"Requeued failed execution {execution_id} "
                            f"(recoverable: {recoverable})"
                        )

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
                self.active_executions_gauge.set(len(self._active_executions))

                # Publish execution started event for workers
                logger.info(f"About to publish ExecutionStartedEvent for {event.execution_id}")
                try:
                    await self._publish_execution_started(event, allocation)
                    logger.info(f"Successfully published ExecutionStartedEvent for {event.execution_id}")
                except Exception as publish_error:
                    logger.error(f"Failed to publish ExecutionStartedEvent for {event.execution_id}: {publish_error}",
                                 exc_info=True)
                    raise

                # Track metrics
                queue_time = start_time - event.timestamp.timestamp()
                priority = getattr(event, 'priority', QueuePriority.NORMAL.value)
                self.queue_time.labels(
                    priority=QueuePriority(priority).name
                ).observe(queue_time)

                scheduling_duration = time.time() - start_time
                self.scheduling_duration.observe(scheduling_duration)
                self.executions_scheduled.labels(status="scheduled").inc()

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
                self.active_executions_gauge.set(len(self._active_executions))
                self.executions_scheduled.labels(status="error").inc()

                # Publish failure event
                await self._publish_scheduling_failed(event, str(e))

    async def _publish_execution_started(
            self,
            request: ExecutionRequestedEvent,
            allocation: ResourceAllocation
    ) -> None:
        """Forward execution request to k8s-worker via EXECUTION_TASKS topic"""
        logger.info(f"Forwarding ExecutionRequestedEvent to k8s-worker for {request.execution_id}")

        # Forward the original request to the k8s-worker via EXECUTION_TASKS topic
        logger.info(f"Sending event to execution_tasks topic for {request.execution_id}")
        if not self.producer:
            logger.error("Producer not initialized")
            return
        
        from app.schemas_avro.event_schemas import KafkaTopic
        await self.producer.send_event(
            event=request,
            topic=KafkaTopic.EXECUTION_TASKS,
            key=str(request.execution_id)
        )
        logger.info(f"ExecutionRequestedEvent forwarded successfully to k8s-worker for {request.execution_id}")

    async def _publish_rate_limit_exceeded(
            self,
            request: ExecutionRequestedEvent,
            wait_time: float,
            limit_type: str
    ) -> None:
        """Publish rate limit exceeded event"""
        # ExecutionFailedEvent requires: execution_id, error, error_type, and metadata
        event = ExecutionFailedEvent(
            execution_id=request.execution_id,
            error=f"Rate limit exceeded: {limit_type}. Wait {wait_time:.0f} seconds.",
            error_type=ExecutionErrorType.PERMISSION_DENIED,
            exit_code=None,
            output=None,
            metadata=request.metadata
        )

        if not self.producer:
            logger.error("Producer not initialized")
            return
        await self.producer.send_event(event=event,
                                       topic=get_topic_for_event(EventType.EXECUTION_FAILED).value,
                                       key=str(request.execution_id))

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
            error=f"Queue full: {error}. Queue size: {queue_stats.get('total_size', 'unknown')}",
            error_type=ExecutionErrorType.RESOURCE_LIMIT,
            exit_code=None,
            output=None,
            metadata=request.metadata
        )

        if not self.producer:
            logger.error("Producer not initialized")
            return
        await self.producer.send_event(event=event,
                                       topic=get_topic_for_event(EventType.EXECUTION_FAILED).value,
                                       key=str(request.execution_id))

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
            error=f"Failed to schedule execution: {error}. "
                  f"Available resources: CPU={resource_stats.available.cpu_cores}, "
                  f"Memory={resource_stats.available.memory_mb}MB",
            error_type=ExecutionErrorType.SYSTEM_ERROR,
            exit_code=None,
            output=None,
            metadata=request.metadata
        )

        if not self.producer:
            logger.error("Producer not initialized")
            return
        await self.producer.send_event(event=event,
                                       topic=get_topic_for_event(EventType.EXECUTION_FAILED).value,
                                       key=str(request.execution_id))

    async def get_status(self) -> dict[str, Any]:
        """Get coordinator status"""
        return {
            "running": self._running,
            "active_executions": len(self._active_executions),
            "queue_stats": await self.queue_manager.get_queue_stats(),
            "resource_stats": await self.resource_manager.get_resource_stats(),
            "rate_limit_stats": {
                "global": await self.rate_limiter.get_remaining_quota(),
                "active_users": len(self.rate_limiter.user_minute_buckets)
            }
        }


async def run_coordinator() -> None:
    """Run the execution coordinator service"""
    # Initialize schema registry
    logger.info("Initializing schema registry for coordinator...")
    schema_registry_manager = create_schema_registry_manager()
    await initialize_event_schemas(schema_registry_manager)
    
    # Initialize producer
    logger.info("Initializing Kafka producer for coordinator...")
    producer = create_unified_producer(schema_registry_manager=schema_registry_manager)
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
    
    # Initialize event store
    logger.info("Initializing event store for coordinator...")
    event_store = create_event_store(
        db=database,
        ttl_days=90
    )
    await event_store.initialize()
    
    coordinator = ExecutionCoordinator(
        producer=producer,
        schema_registry_manager=schema_registry_manager,
        event_store=event_store
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
    asyncio.run(run_coordinator())
