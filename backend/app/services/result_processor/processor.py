"""Result processor service for handling execution completion events."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum, auto
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.core.database_context import DatabaseConfig, create_database_connection
from app.core.logging import logger
from app.events.core.consumer import ConsumerConfig, UnifiedConsumer
from app.events.core.consumer_group_names import GroupId
from app.events.core.producer import UnifiedProducer, create_unified_producer
from app.events.schema.schema_registry import SchemaRegistryManager
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
from app.services.idempotency import create_idempotency_manager

MEGABYTE: int = 1024 * 1024


class ProcessingState(StrEnum):
    """Processing state enumeration."""
    IDLE = auto()
    PROCESSING = auto()
    STOPPED = auto()




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
    batch_size: int = Field(default=10)
    processing_timeout: int = Field(default=300)


@dataclass
class ProcessingContext:
    """Context for processing events."""
    config: ResultProcessorConfig
    producer: UnifiedProducer
    database: AsyncIOMotorDatabase


class ResultProcessor:
    """Service for processing execution completion events and storing results."""

    def __init__(
            self,
            config: ResultProcessorConfig | None = None,
            database: AsyncIOMotorDatabase | None = None,
            producer: UnifiedProducer | None = None,
            schema_registry_manager: SchemaRegistryManager | None = None
    ) -> None:
        """Initialize the result processor."""
        self.config = config or ResultProcessorConfig()
        self.database = database
        self._producer = producer
        self._producer_provided = producer is not None
        self._schema_registry_manager = schema_registry_manager

        self._state = ProcessingState.IDLE
        self._processed_count = 0
        self._failed_count = 0
        self._last_processed_time: datetime | None = None

        self._consumer: UnifiedConsumer | None = None
        self._context: ProcessingContext | None = None

    async def start(self) -> None:
        """Start the result processor."""
        if self._state != ProcessingState.IDLE:
            logger.warning(f"Cannot start processor in state: {self._state}")
            return

        logger.info("Starting ResultProcessor...")

        if self.database is None:
            raise RuntimeError("Database not provided to ResultProcessor")

        self._context = await self._initialize_context()
        await self._create_indexes()
        self._consumer = await self._create_consumer()
        self._state = ProcessingState.PROCESSING

        logger.info("ResultProcessor started successfully")

    async def stop(self) -> None:
        """Stop the result processor."""
        if self._state == ProcessingState.STOPPED:
            return

        logger.info("Stopping ResultProcessor...")
        self._state = ProcessingState.STOPPED

        if self._consumer:
            await self._consumer.stop()

        if self._producer and not self._producer_provided:
            await self._producer.stop()

        logger.info("ResultProcessor stopped")

    async def _initialize_context(self) -> ProcessingContext:
        """Initialize processing context."""
        assert self.database is not None

        if not self._producer:
            self._producer = create_unified_producer(schema_registry_manager=self._schema_registry_manager)
            await self._producer.start()

        return ProcessingContext(
            config=self.config,
            producer=self._producer,
            database=self.database
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

        consumer = UnifiedConsumer(consumer_config, self._schema_registry_manager)
        consumer.register_handler("*", self._process_event)
        await consumer.start()

        return consumer

    async def _create_indexes(self) -> None:
        """Create database indexes."""
        assert self._context is not None

        results_collection = self._context.database.execution_results

        await asyncio.gather(
            results_collection.create_index("execution_id", unique=True),
            results_collection.create_index("created_at"),
            results_collection.create_index([("user_id", 1), ("created_at", -1)])
        )


    async def _process_event(self, event: ExecutionCompletedEvent | ExecutionFailedEvent | ExecutionTimeoutEvent | Any,
                             _: Any = None) -> None:
        """Process a single event using pattern matching."""
        execution_id: str | None = None
        
        if isinstance(event, (ExecutionCompletedEvent, ExecutionFailedEvent, ExecutionTimeoutEvent)):
            execution_id = event.execution_id

        logger.info(
            f"Processing {type(event).__name__} for execution_id: "
            f"{execution_id or 'unknown'}"
        )

        try:
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

            self._processed_count += 1
            self._last_processed_time = datetime.now(UTC)

        except Exception as e:
            logger.error(f"Failed to process event: {e}", exc_info=True)
            self._failed_count += 1

            if execution_id:
                await self._publish_result_failed(execution_id, str(e))

    async def _handle_completed(self, event: ExecutionCompletedEvent) -> None:
        """Handle execution completed event."""
        assert self._context is not None

        result = await self._store_result(
            execution_id=event.execution_id,
            status=ExecutionStatus.COMPLETED,
            exit_code=event.exit_code,
            output=event.output,
            error="",
            execution_time_ms=event.runtime_ms,
            metadata=event.metadata,
        )

        await self._update_execution_status(
            event.execution_id,
            ExecutionStatus.COMPLETED,
            output=event.output,
            error="",
            execution_time_ms=event.runtime_ms,
            exit_code=event.exit_code,
        )

        await self._publish_result_stored(event.execution_id, result)

    async def _handle_failed(self, event: ExecutionFailedEvent) -> None:
        """Handle execution failed event."""
        assert self._context is not None

        result = await self._store_result(
            execution_id=event.execution_id,
            status=ExecutionStatus.FAILED,
            exit_code=event.exit_code or -1,
            output=event.output or "",
            error=event.error,
            execution_time_ms=0,  # Failed executions don't have runtime info
            metadata=event.metadata,
            error_type=event.error_type,
            error_details={"original_error": event.error},
        )

        await self._update_execution_status(
            event.execution_id,
            ExecutionStatus.FAILED,
            output=event.output or "",
            error=event.error,
            exit_code=event.exit_code
        )

        await self._publish_result_stored(event.execution_id, result)

    async def _handle_timeout(self, event: ExecutionTimeoutEvent) -> None:
        """Handle execution timeout event."""
        assert self._context is not None

        result = await self._store_result(
            execution_id=event.execution_id,
            status=ExecutionStatus.TIMEOUT,
            exit_code=-1,
            output=event.partial_output or "",
            error="Execution timed out",
            execution_time_ms=event.timeout_seconds * 1000,
            metadata=event.metadata,
            error_type="Timeout",
            error_details={"timeout_seconds": event.timeout_seconds},
        )

        await self._update_execution_status(
            event.execution_id,
            ExecutionStatus.TIMEOUT,
            output=event.partial_output or "",
            error="Execution timed out",
            execution_time_ms=event.timeout_seconds * 1000
        )

        await self._publish_result_stored(event.execution_id, result)

    async def _store_result(
            self,
            execution_id: str,
            status: ExecutionStatus,
            exit_code: int,
            output: str,
            error: str,
            execution_time_ms: float,
            metadata: EventMetadata,
            error_type: str | None = None,
            error_details: dict[str, Any] | None = None,
            resource_usage: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Store execution result in database."""
        assert self._context is not None

        result: dict[str, Any] = {
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

        if error_type:
            result["error_type"] = error_type
        if error_details:
            result["error_details"] = error_details
        if resource_usage:
            result["resource_usage"] = {
                "cpu_seconds": float(resource_usage.get("cpu_seconds", 0)),
                "memory_bytes": float(resource_usage.get("memory_bytes", 0))
            }

        await self._context.database.execution_results.replace_one(
            {"_id": result["_id"]},
            result,
            upsert=True
        )

        return result

    async def _update_execution_status(
            self,
            execution_id: str,
            status: ExecutionStatus,
            output: str | None = None,
            error: str | None = None,
            execution_time_ms: float | None = None,
            exit_code: int | None = None,
            resource_usage: dict[str, float] | None = None
    ) -> None:
        """Update execution status in database."""
        assert self._context is not None

        update_data: dict[str, Any] = {
            "status": status.value,
            "updated_at": datetime.now(UTC),
        }

        if output is not None:
            update_data["output"] = output
        if error is not None:
            update_data["errors"] = error
        if execution_time_ms is not None:
            update_data["execution_time"] = execution_time_ms / 1000.0
        if exit_code is not None:
            update_data["exit_code"] = exit_code

        if resource_usage and execution_time_ms:
            execution_seconds = execution_time_ms / 1000.0
            cpu_seconds = float(resource_usage.get("cpu_seconds", 0))
            memory_bytes = float(resource_usage.get("memory_bytes", 0))

            cpu_millicores = (cpu_seconds / execution_seconds * 1000) if execution_seconds > 0 else 0.0
            memory_mib = memory_bytes / MEGABYTE

            update_data["resource_usage"] = {
                "execution_time": execution_seconds,
                "cpu_usage": round(cpu_millicores, 3),
                "memory_usage": round(memory_mib, 3)
            }

        result = await self._context.database.executions.update_one(
            {"execution_id": execution_id},
            {"$set": update_data}
        )

        if result.modified_count == 0:
            logger.warning(f"No execution found with ID {execution_id}")

    async def _publish_result_stored(
            self,
            execution_id: str,
            result: dict[str, Any]
    ) -> None:
        """Publish result stored event."""
        assert self._context is not None

        event = ResultStoredEvent(
            execution_id=execution_id,
            storage_key=execution_id,
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
            execution_id: str,
            error_message: str
    ) -> None:
        """Publish result processing failed event."""
        assert self._context is not None

        event = ResultFailedEvent(
            execution_id=execution_id,
            error=error_message,
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


    async def get_status(self) -> dict[str, Any]:
        """Get processor status."""
        return {
            "state": self._state.value,
            "processed_count": self._processed_count,
            "failed_count": self._failed_count,
            "last_processed_time": (
                self._last_processed_time.isoformat()
                if self._last_processed_time
                else None
            ),
            "consumer_active": self._consumer is not None,
        }


async def run_result_processor() -> None:
    """Run result processor as standalone service."""
    db_connection = None
    idempotency_manager = None
    producer = None
    processor = None
    
    try:
        settings = get_settings()
        db_config = DatabaseConfig(
            mongodb_url=settings.MONGODB_URL,
            db_name=settings.PROJECT_NAME,
            server_selection_timeout_ms=5000,
            connect_timeout_ms=5000
        )

        db_connection = create_database_connection(db_config)
        await db_connection.connect()
        database = db_connection.database

        idempotency_manager = create_idempotency_manager(database)
        await idempotency_manager.initialize()
        logger.info("Initialized idempotency manager")

        from app.events.schema.schema_registry import create_schema_registry_manager
        schema_registry_manager = create_schema_registry_manager()

        producer = create_unified_producer(schema_registry_manager=schema_registry_manager)
        await producer.start()

        processor = ResultProcessor(
            database=database,
            producer=producer,
            schema_registry_manager=schema_registry_manager
        )
        
        await processor.start()

        while True:
            await asyncio.sleep(60)
            status = await processor.get_status()
            logger.info(f"ResultProcessor status: {status}")

    except asyncio.CancelledError:
        logger.info("ResultProcessor cancelled")
    finally:
        if processor is not None:
            await processor.stop()
        if producer is not None:
            await producer.stop()
        if idempotency_manager is not None:
            await idempotency_manager.close()
        if db_connection is not None:
            await db_connection.disconnect()
