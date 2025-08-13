"""Result processor service for handling execution completion events.

This module processes execution completion events from Kafka and stores
the results in MongoDB using modern Python 3.12+ patterns.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum, auto
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.core.logging import logger
from app.db.mongodb import DatabaseManager
from app.events.core.consumer import ConsumerConfig, UnifiedConsumer
from app.events.core.consumer_group_names import GroupId
from app.events.core.producer import get_producer
from app.schemas_avro.event_schemas import (
    EventMetadata,
    EventType,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
    KafkaTopic,
    ResultFailedEvent,
    ResultStoredEvent,
    StorageType,
)
from app.schemas_pydantic.execution import ExecutionStatus
from app.services.idempotency.idempotency_manager import IdempotencyManagerSingleton
from app.services.result_processor.log_extractor import LogExtractor
from app.services.result_processor.resource_cleaner import ResourceCleaner

# Type aliases
type ExecutionId = str
type EventHandler = Any  # Complex callable type
type ResultDict = dict[str, Any]
type ResourceUsageDict = dict[str, float]

# Constants
MEGABYTE: int = 1024 * 1024
KILOBYTE: int = 1024


class ProcessingState(StrEnum):
    """Processing state enumeration."""
    IDLE = auto()
    PROCESSING = auto()
    STOPPED = auto()


class EventProcessor(Protocol):
    """Protocol for event processing methods."""

    async def __call__(self, event: Any) -> None:
        """Process an event."""
        ...


@dataclass(frozen=True, slots=True)
class ProcessingMetrics:
    """Immutable processing metrics."""
    processed_count: int = 0
    failed_count: int = 0
    last_processed_time: datetime | None = None

    def increment_processed(self) -> 'ProcessingMetrics':
        """Return new metrics with incremented processed count."""
        return ProcessingMetrics(
            processed_count=self.processed_count + 1,
            failed_count=self.failed_count,
            last_processed_time=datetime.now(UTC)
        )

    def increment_failed(self) -> 'ProcessingMetrics':
        """Return new metrics with incremented failed count."""
        return ProcessingMetrics(
            processed_count=self.processed_count,
            failed_count=self.failed_count + 1,
            last_processed_time=self.last_processed_time
        )


@dataclass(frozen=True, slots=True)
class LogData:
    """Immutable log data container."""
    stdout: str = ""
    stderr: str = ""

    @classmethod
    def empty(cls) -> 'LogData':
        """Create empty log data."""
        return cls()


class ResultProcessorConfig(BaseModel):
    """Configuration for result processor."""

    model_config = ConfigDict(frozen=True)

    consumer_group: str = Field(default=GroupId.RESULT_PROCESSOR)
    topics: list[str] = Field(
        default_factory=lambda: [
            EventType.EXECUTION_COMPLETED.value,
            EventType.EXECUTION_FAILED.value,
            EventType.EXECUTION_TIMEOUT.value
        ]
    )
    result_topic: str = Field(default=KafkaTopic.RESULT_EVENTS.value)

    max_log_size_bytes: int = Field(default=10 * MEGABYTE)
    log_extraction_timeout: int = Field(default=30)
    cleanup_timeout: int = Field(default=60)

    enable_resource_cleanup: bool = Field(default=True)
    cleanup_delay_seconds: int = Field(default=5)

    batch_size: int = Field(default=10)
    processing_timeout: int = Field(default=300)


@dataclass
class ProcessingContext:
    """Context for processing events."""
    config: ResultProcessorConfig
    producer: Any
    log_extractor: LogExtractor
    resource_cleaner: ResourceCleaner
    db_manager: DatabaseManager

    # Lazy-loaded database collections
    _executions_collection: Any = field(init=False, default=None)
    _results_collection: Any = field(init=False, default=None)

    @property
    def executions_collection(self) -> Any:
        """Get executions collection (lazy-loaded)."""
        if self._executions_collection is None:
            db = self.db_manager.get_database()
            self._executions_collection = db.executions
        return self._executions_collection

    @property
    def results_collection(self) -> Any:
        """Get results collection (lazy-loaded)."""
        if self._results_collection is None:
            db = self.db_manager.get_database()
            self._results_collection = db.execution_results
        return self._results_collection


class ResultProcessor:
    """Service for processing pod completion events using modern patterns."""

    def __init__(
            self,
            config: ResultProcessorConfig | None = None,
            db_manager: DatabaseManager | None = None
    ) -> None:
        """Initialize the result processor."""
        self.config = config or ResultProcessorConfig()
        self.db_manager = db_manager

        self._state = ProcessingState.IDLE
        self._metrics = ProcessingMetrics()
        self._tasks: list[asyncio.Task[Any]] = []

        # Components (initialized on start)
        self._consumer: UnifiedConsumer | None = None
        self._context: ProcessingContext | None = None

    async def start(self) -> None:
        """Start the result processor."""
        if self._state != ProcessingState.IDLE:
            logger.warning(f"Cannot start processor in state: {self._state}")
            return

        logger.info("Starting ResultProcessor...")

        # Validate database manager
        if not self.db_manager:
            raise RuntimeError("DatabaseManager not provided to ResultProcessor")

        # Initialize components and context
        self._context = await self._initialize_context()
        await self._create_indexes()

        # Initialize consumer
        self._consumer = await self._create_consumer()

        # Start processing
        self._state = ProcessingState.PROCESSING
        self._tasks.append(asyncio.create_task(self._consume_events()))

        logger.info("ResultProcessor started successfully")

    async def stop(self) -> None:
        """Stop the result processor."""
        if self._state == ProcessingState.STOPPED:
            return

        logger.info("Stopping ResultProcessor...")
        self._state = ProcessingState.STOPPED

        # Cancel tasks
        for task in self._tasks:
            task.cancel()

        # Wait for cancellation
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        # Stop consumer
        if self._consumer:
            await self._consumer.stop()

        logger.info("ResultProcessor stopped")

    async def _initialize_context(self) -> ProcessingContext:
        """Initialize processing context."""
        assert self.db_manager is not None

        producer = await get_producer()

        return ProcessingContext(
            config=self.config,
            producer=producer,
            log_extractor=LogExtractor(),
            resource_cleaner=ResourceCleaner(),
            db_manager=self.db_manager
        )

    async def _create_consumer(self) -> UnifiedConsumer:
        """Create and configure Kafka consumer."""
        consumer_config = ConsumerConfig(
            group_id=self.config.consumer_group,
            topics=self.config.topics,
            max_poll_records=1,
            enable_auto_commit=True,
            auto_offset_reset="earliest"
        )

        consumer = UnifiedConsumer(consumer_config)
        consumer.register_handler("*", self._process_event)
        await consumer.start()

        return consumer

    async def _create_indexes(self) -> None:
        """Create database indexes."""
        assert self._context is not None

        results_collection = self._context.results_collection

        # Create indexes concurrently
        await asyncio.gather(
            results_collection.create_index("execution_id", unique=True),
            results_collection.create_index("created_at"),
            results_collection.create_index([("user_id", 1), ("created_at", -1)])
        )

    async def _consume_events(self) -> None:
        """Main consumer loop (minimal, just keeps alive)."""
        logger.info("Starting event consumption...")

        while self._state == ProcessingState.PROCESSING:
            await asyncio.sleep(1)

    async def _process_event(self, event: Any, _: Any = None) -> None:
        """Process a single event using pattern matching."""
        execution_id = None
        match event:
            case ExecutionCompletedEvent() | ExecutionFailedEvent() | ExecutionTimeoutEvent():
                execution_id = event.execution_id
            case _:
                pass

        logger.info(
            f"Processing {type(event).__name__} for execution_id: "
            f"{execution_id or 'unknown'}"
        )

        # Process with metrics tracking
        try:
            # Pattern matching on event type
            match event:
                case ExecutionCompletedEvent():
                    await self._handle_completed(event)
                case ExecutionFailedEvent():
                    await self._handle_failed(event)
                case ExecutionTimeoutEvent():
                    await self._handle_timeout(event)
                case _:
                    logger.warning(f"No handler for event type: {type(event).__name__}")
                    return

            self._metrics = self._metrics.increment_processed()

        except Exception as e:
            logger.error(f"Failed to process event: {e}", exc_info=True)
            self._metrics = self._metrics.increment_failed()

            # Publish failure if we can get execution_id
            execution_id = event.execution_id if isinstance(event, (ExecutionCompletedEvent, ExecutionFailedEvent,
                                                                    ExecutionTimeoutEvent)) else None
            if execution_id:
                await self._publish_result_failed(execution_id, str(e))

    async def _handle_completed(self, event: ExecutionCompletedEvent) -> None:
        """Handle execution completed event."""
        assert self._context is not None

        # Store result
        result = await self._store_result(
            execution_id=event.execution_id,
            status=ExecutionStatus.COMPLETED,
            exit_code=event.exit_code,
            output=event.output,
            error="",
            execution_time_ms=event.runtime_ms,
            metadata=event.metadata,
        )

        # Update execution
        await self._update_execution_status(
            event.execution_id,
            ExecutionStatus.COMPLETED,
            output=event.output,
            error="",
            execution_time_ms=event.runtime_ms,
            exit_code=event.exit_code,
        )

        # Publish result stored
        await self._publish_result_stored(event.execution_id, result)

        # Note: Execution events don't have pod_name field
        # Cleanup would need to be triggered by pod events instead

    async def _handle_failed(self, event: ExecutionFailedEvent) -> None:
        """Handle execution failed event."""
        assert self._context is not None

        # Extract logs if pod_name available
        logs = await self._extract_logs_safe(event)

        # Use event's output/error or extracted logs
        output = event.output or logs.stdout
        error = event.error or logs.stderr

        # Store result
        result = await self._store_result(
            execution_id=event.execution_id,
            status=ExecutionStatus.FAILED,
            exit_code=event.exit_code or -1,
            output=output,
            error=error,
            execution_time_ms=0,  # Not provided in event
            metadata=event.metadata,
            error_type=event.error_type,
            error_details={"original_error": event.error},
        )

        # Update execution
        await self._update_execution_status(
            event.execution_id,
            ExecutionStatus.FAILED,
            output=output,
            error=error,
            exit_code=event.exit_code
        )

        # Publish result stored
        await self._publish_result_stored(event.execution_id, result)

        # Note: Execution events don't have pod_name field
        # Cleanup would need to be triggered by pod events instead

    async def _handle_timeout(self, event: ExecutionTimeoutEvent) -> None:
        """Handle execution timeout event."""
        assert self._context is not None

        # Extract logs if available
        logs = await self._extract_logs_safe(event)

        output = event.partial_output or logs.stdout
        error = logs.stderr or "Execution timed out"

        # Store result
        result = await self._store_result(
            execution_id=event.execution_id,
            status=ExecutionStatus.TIMEOUT,
            exit_code=-1,
            output=output,
            error=error,
            execution_time_ms=event.timeout_seconds * 1000,
            metadata=event.metadata,
            error_type="Timeout",
            error_details={"timeout_seconds": event.timeout_seconds},
        )

        # Update execution
        await self._update_execution_status(
            event.execution_id,
            ExecutionStatus.TIMEOUT,
            output=output,
            error=error,
            execution_time_ms=event.timeout_seconds * 1000
        )

        # Publish result stored
        await self._publish_result_stored(event.execution_id, result)

        # Note: Execution events don't have pod_name field
        # Cleanup would need to be triggered by pod events instead

    async def _extract_logs_safe(self, event: Any) -> LogData:
        """Safely extract logs from pod if available."""
        assert self._context is not None

        # Check if event might have pod_name without using hasattr
        try:
            pod_name = event.pod_name
            namespace = event.namespace
        except AttributeError:
            return LogData.empty()

        if not pod_name:
            return LogData.empty()

        try:
            log_dict = await self._context.log_extractor.extract_logs(
                pod_name=pod_name,
                namespace=namespace or 'default',
                timeout=self.config.log_extraction_timeout,
                max_size=self.config.max_log_size_bytes,
            )
            return LogData(
                stdout=log_dict.get("stdout", ""),
                stderr=log_dict.get("stderr", "")
            )
        except Exception as e:
            logger.warning(f"Could not extract logs: {e}")
            return LogData.empty()

    async def _store_result(
            self,
            execution_id: ExecutionId,
            status: ExecutionStatus,
            exit_code: int,
            output: str,
            error: str,
            execution_time_ms: float,
            metadata: EventMetadata,
            error_type: str | None = None,
            error_details: dict[str, Any] | None = None,
            resource_usage: ResourceUsageDict | None = None,
    ) -> ResultDict:
        """Store execution result in database."""
        assert self._context is not None

        result: ResultDict = {
            "_id": execution_id,
            "execution_id": execution_id,
            "status": status.value,
            "exit_code": exit_code,
            "output": output,
            "error": error,
            "execution_time_ms": execution_time_ms,
            "created_at": datetime.now(UTC),
            "metadata": metadata.model_dump(),
        }

        # Add optional fields
        if error_type:
            result["error_type"] = error_type
        if error_details:
            result["error_details"] = error_details
        if resource_usage:
            result["resource_usage"] = {
                "cpu_seconds": float(resource_usage.get("cpu_seconds", 0)),
                "memory_bytes": float(resource_usage.get("memory_bytes", 0))
            }

        # Upsert result
        await self._context.results_collection.replace_one(
            {"_id": result["_id"]},
            result,
            upsert=True
        )

        return result

    async def _update_execution_status(
            self,
            execution_id: ExecutionId,
            status: ExecutionStatus,
            output: str | None = None,
            error: str | None = None,
            execution_time_ms: float | None = None,
            exit_code: int | None = None,
            resource_usage: ResourceUsageDict | None = None
    ) -> None:
        """Update execution status in database."""
        assert self._context is not None

        update_data: dict[str, Any] = {
            "status": status.value,
            "updated_at": datetime.now(UTC),
        }

        # Add optional updates
        if output is not None:
            update_data["output"] = output
        if error is not None:
            update_data["errors"] = error
        if execution_time_ms is not None:
            update_data["execution_time"] = execution_time_ms / 1000.0
        if exit_code is not None:
            update_data["exit_code"] = exit_code

        # Process resource usage if provided
        if resource_usage and execution_time_ms:
            execution_seconds = execution_time_ms / 1000.0
            cpu_seconds = float(resource_usage.get("cpu_seconds", 0))
            memory_bytes = float(resource_usage.get("memory_bytes", 0))

            # Calculate display values
            cpu_millicores = (cpu_seconds / execution_seconds * 1000) if execution_seconds > 0 else 0.0
            memory_mib = memory_bytes / MEGABYTE

            update_data["resource_usage"] = {
                "execution_time": execution_seconds,
                "cpu_usage": round(cpu_millicores, 3),
                "memory_usage": round(memory_mib, 3)
            }

        # Update document
        result = await self._context.executions_collection.update_one(
            {"execution_id": execution_id},
            {"$set": update_data}
        )

        if result.modified_count == 0:
            logger.warning(f"No execution found with ID {execution_id}")

    async def _publish_result_stored(
            self,
            execution_id: ExecutionId,
            result: ResultDict
    ) -> None:
        """Publish result stored event."""
        assert self._context is not None

        # Fix: Use storage_key instead of result_id
        event = ResultStoredEvent(
            execution_id=(execution_id),
            storage_key=execution_id,  # Using execution_id as storage key
            size_bytes=len(result.get("output", "")) + len(result.get("error", "")),
            storage_type=StorageType.DATABASE,
            metadata=EventMetadata(
                service_name=GroupId.RESULT_PROCESSOR,
                service_version="1.0.0",
            ),
        )

        await self._context.producer.send_event(
            event,
            self.config.result_topic,
            key=execution_id
        )

    async def _publish_result_failed(
            self,
            execution_id: ExecutionId,
            error_message: str
    ) -> None:
        """Publish result processing failed event."""
        assert self._context is not None

        # Fix: Use 'error' field instead of 'error_message'
        event = ResultFailedEvent(
            execution_id=execution_id,
            error=error_message,  # Fixed field name
            partial_result=None,
            metadata=EventMetadata(
                service_name=GroupId.RESULT_PROCESSOR,
                service_version="1.0.0",
            ),
        )

        await self._context.producer.send_event(
            event,
            self.config.result_topic,
            key=execution_id if execution_id else None
        )

    async def _schedule_cleanup(self, event: Any) -> None:
        """Schedule resource cleanup with delay."""
        await asyncio.sleep(self.config.cleanup_delay_seconds)

        task = asyncio.create_task(self._cleanup_resources(event))
        self._tasks.append(task)

    async def _cleanup_resources(self, event: Any) -> None:
        """Clean up pod resources."""
        assert self._context is not None

        try:
            # Safe attribute access
            try:
                pod_name = event.pod_name
                namespace = event.namespace or 'default'
                execution_id = event.execution_id
            except AttributeError as e:
                logger.error(f"Event missing required attributes: {e}")
                return

            await self._context.resource_cleaner.cleanup_pod_resources(
                pod_name=pod_name,
                namespace=namespace,
                execution_id=execution_id,
                timeout=self.config.cleanup_timeout,
            )
            logger.info(f"Cleaned up resources for pod: {pod_name}")
        except Exception as e:
            logger.error(f"Failed to cleanup resources: {e}")

    async def get_status(self) -> dict[str, Any]:
        """Get processor status."""
        return {
            "state": self._state.value,
            "processed_count": self._metrics.processed_count,
            "failed_count": self._metrics.failed_count,
            "last_processed_time": (
                self._metrics.last_processed_time.isoformat()
                if self._metrics.last_processed_time
                else None
            ),
            "consumer_active": self._consumer is not None,
        }


async def run_result_processor() -> None:
    """Run result processor as standalone service."""
    # Initialize database
    settings = get_settings()
    db_manager = DatabaseManager(settings)
    await db_manager.connect_to_database()

    # Initialize idempotency manager
    await IdempotencyManagerSingleton.get_instance(db_manager)
    logger.info("Initialized idempotency manager")

    # Create and start processor
    processor = ResultProcessor(db_manager=db_manager)

    try:
        await processor.start()

        # Run until cancelled
        while True:
            await asyncio.sleep(60)

            # Log status periodically
            status = await processor.get_status()
            logger.info(f"ResultProcessor status: {status}")

    except asyncio.CancelledError:
        logger.info("ResultProcessor cancelled")
    finally:
        await processor.stop()
        await IdempotencyManagerSingleton.close_instance()
        await db_manager.close_database_connection()
