import asyncio
from enum import auto
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.container import create_result_processor_container
from app.core.exceptions import ServiceError
from app.core.lifecycle import LifecycleEnabled
from app.core.logging import logger
from app.core.metrics.context import get_execution_metrics
from app.core.utils import StringEnum
from app.db.repositories.execution_repository import ExecutionRepository
from app.domain.enums.events import EventType
from app.domain.enums.execution import ExecutionStatus
from app.domain.enums.kafka import GroupId, KafkaTopic
from app.domain.enums.storage import ExecutionErrorType, StorageType
from app.domain.execution import ExecutionResultDomain
from app.events.core import ConsumerConfig, EventDispatcher, UnifiedConsumer, UnifiedProducer
from app.infrastructure.kafka import BaseEvent
from app.infrastructure.kafka.events.execution import (
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
)
from app.infrastructure.kafka.events.metadata import AvroEventMetadata as EventMetadata
from app.infrastructure.kafka.events.system import (
    ResultFailedEvent,
    ResultStoredEvent,
)
from app.services.idempotency import IdempotencyManager
from app.services.idempotency.middleware import IdempotentConsumerWrapper
from app.settings import get_settings


class ProcessingState(StringEnum):
    """Processing state enumeration."""

    IDLE = auto()
    PROCESSING = auto()
    STOPPED = auto()


class ResultProcessorConfig(BaseModel):
    """Configuration for result processor."""

    model_config = ConfigDict(frozen=True)

    consumer_group: GroupId = Field(default=GroupId.RESULT_PROCESSOR)
    topics: list[KafkaTopic] = Field(
        default_factory=lambda: [
            KafkaTopic.EXECUTION_COMPLETED,
            KafkaTopic.EXECUTION_FAILED,
            KafkaTopic.EXECUTION_TIMEOUT,
        ]
    )
    result_topic: KafkaTopic = Field(default=KafkaTopic.EXECUTION_RESULTS)
    batch_size: int = Field(default=10)
    processing_timeout: int = Field(default=300)


class ResultProcessor(LifecycleEnabled):
    """Service for processing execution completion events and storing results."""

    def __init__(
        self, execution_repo: ExecutionRepository, producer: UnifiedProducer, idempotency_manager: IdempotencyManager
    ) -> None:
        """Initialize the result processor."""
        self.config = ResultProcessorConfig()
        self._execution_repo = execution_repo
        self._producer = producer
        self._metrics = get_execution_metrics()
        self._idempotency_manager: IdempotencyManager = idempotency_manager
        self._state = ProcessingState.IDLE
        self._consumer: IdempotentConsumerWrapper | None = None
        self._dispatcher: EventDispatcher | None = None

    async def start(self) -> None:
        """Start the result processor."""
        if self._state != ProcessingState.IDLE:
            logger.warning(f"Cannot start processor in state: {self._state}")
            return

        logger.info("Starting ResultProcessor...")

        # Initialize idempotency manager (safe to call multiple times)
        await self._idempotency_manager.initialize()
        logger.info("Idempotency manager initialized for ResultProcessor")

        self._dispatcher = self._create_dispatcher()
        self._consumer = await self._create_consumer()
        self._state = ProcessingState.PROCESSING
        logger.info("ResultProcessor started successfully with idempotency protection")

    async def stop(self) -> None:
        """Stop the result processor."""
        if self._state == ProcessingState.STOPPED:
            return

        logger.info("Stopping ResultProcessor...")
        self._state = ProcessingState.STOPPED

        if self._consumer:
            await self._consumer.stop()

        await self._idempotency_manager.close()
        await self._producer.stop()
        logger.info("ResultProcessor stopped")

    def _create_dispatcher(self) -> EventDispatcher:
        """Create and configure event dispatcher with handlers."""
        dispatcher = EventDispatcher()

        # Register handlers for specific event types
        dispatcher.register_handler(EventType.EXECUTION_COMPLETED, self._handle_completed_wrapper)
        dispatcher.register_handler(EventType.EXECUTION_FAILED, self._handle_failed_wrapper)
        dispatcher.register_handler(EventType.EXECUTION_TIMEOUT, self._handle_timeout_wrapper)

        return dispatcher

    async def _create_consumer(self) -> IdempotentConsumerWrapper:
        """Create and configure idempotent Kafka consumer."""
        settings = get_settings()
        consumer_config = ConsumerConfig(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=f"{self.config.consumer_group}.{settings.KAFKA_GROUP_SUFFIX}",
            max_poll_records=1,
            enable_auto_commit=True,
            auto_offset_reset="earliest",
        )

        # Create consumer with schema registry and dispatcher
        if not self._dispatcher:
            raise RuntimeError("Event dispatcher not initialized")

        base_consumer = UnifiedConsumer(consumer_config, event_dispatcher=self._dispatcher)
        wrapper = IdempotentConsumerWrapper(
            consumer=base_consumer,
            idempotency_manager=self._idempotency_manager,
            dispatcher=self._dispatcher,
            default_key_strategy="content_hash",
            default_ttl_seconds=7200,
            enable_for_all_handlers=True,
        )
        await wrapper.start(self.config.topics)
        return wrapper

    # Wrappers accepting BaseEvent to satisfy dispatcher typing

    async def _handle_completed_wrapper(self, event: BaseEvent) -> None:
        assert isinstance(event, ExecutionCompletedEvent)
        await self._handle_completed(event)

    async def _handle_failed_wrapper(self, event: BaseEvent) -> None:
        assert isinstance(event, ExecutionFailedEvent)
        await self._handle_failed(event)

    async def _handle_timeout_wrapper(self, event: BaseEvent) -> None:
        assert isinstance(event, ExecutionTimeoutEvent)
        await self._handle_timeout(event)

    async def _handle_completed(self, event: ExecutionCompletedEvent) -> None:
        """Handle execution completed event."""

        exec_obj = await self._execution_repo.get_execution(event.execution_id)
        if exec_obj is None:
            raise ServiceError(message=f"Execution {event.execution_id} not found", status_code=404)

        lang_and_version = f"{exec_obj.lang}-{exec_obj.lang_version}"

        # Record metrics for successful completion
        self._metrics.record_script_execution(ExecutionStatus.COMPLETED, lang_and_version)
        runtime_seconds = event.resource_usage.execution_time_wall_seconds
        self._metrics.record_execution_duration(runtime_seconds, lang_and_version)

        # Record memory utilization
        memory_mib = event.resource_usage.peak_memory_kb / 1024
        self._metrics.record_memory_usage(memory_mib, lang_and_version)

        # Calculate and record memory utilization percentage
        settings_limit = get_settings().K8S_POD_MEMORY_LIMIT
        memory_limit_mib = int(settings_limit.rstrip("Mi"))  # TODO: Less brittle acquisition of limit
        memory_percent = (memory_mib / memory_limit_mib) * 100
        self._metrics.memory_utilization_percent.record(
            memory_percent, attributes={"lang_and_version": lang_and_version}
        )

        result = ExecutionResultDomain(
            execution_id=event.execution_id,
            status=ExecutionStatus.COMPLETED,
            exit_code=event.exit_code,
            stdout=event.stdout,
            stderr=event.stderr,
            resource_usage=event.resource_usage,
            metadata=event.metadata.model_dump(),
        )

        try:
            await self._execution_repo.write_terminal_result(result)
            await self._publish_result_stored(result)
        except Exception as e:
            logger.error(f"Failed to handle ExecutionCompletedEvent: {e}", exc_info=True)
            await self._publish_result_failed(event.execution_id, str(e))

    async def _handle_failed(self, event: ExecutionFailedEvent) -> None:
        """Handle execution failed event."""

        # Fetch execution to get language and version for metrics
        exec_obj = await self._execution_repo.get_execution(event.execution_id)
        if exec_obj is None:
            raise ServiceError(message=f"Execution {event.execution_id} not found", status_code=404)

        self._metrics.record_error(event.error_type)
        lang_and_version = f"{exec_obj.lang}-{exec_obj.lang_version}"

        self._metrics.record_script_execution(ExecutionStatus.FAILED, lang_and_version)
        result = ExecutionResultDomain(
            execution_id=event.execution_id,
            status=ExecutionStatus.FAILED,
            exit_code=event.exit_code or -1,
            stdout=event.stdout,
            stderr=event.stderr,
            resource_usage=event.resource_usage,
            metadata=event.metadata.model_dump(),
            error_type=event.error_type,
        )
        try:
            await self._execution_repo.write_terminal_result(result)
            await self._publish_result_stored(result)
        except Exception as e:
            logger.error(f"Failed to handle ExecutionFailedEvent: {e}", exc_info=True)
            await self._publish_result_failed(event.execution_id, str(e))

    async def _handle_timeout(self, event: ExecutionTimeoutEvent) -> None:
        """Handle execution timeout event."""

        exec_obj = await self._execution_repo.get_execution(event.execution_id)
        if exec_obj is None:
            raise ServiceError(message=f"Execution {event.execution_id} not found", status_code=404)

        self._metrics.record_error(ExecutionErrorType.TIMEOUT)
        lang_and_version = f"{exec_obj.lang}-{exec_obj.lang_version}"

        # Record metrics for timeout
        self._metrics.record_script_execution(ExecutionStatus.TIMEOUT, lang_and_version)
        self._metrics.record_execution_duration(event.timeout_seconds, lang_and_version)

        result = ExecutionResultDomain(
            execution_id=event.execution_id,
            status=ExecutionStatus.TIMEOUT,
            exit_code=-1,
            stdout=event.stdout,
            stderr=event.stderr,
            resource_usage=event.resource_usage,
            metadata=event.metadata.model_dump(),
            error_type=ExecutionErrorType.TIMEOUT,
        )
        try:
            await self._execution_repo.write_terminal_result(result)
            await self._publish_result_stored(result)
        except Exception as e:
            logger.error(f"Failed to handle ExecutionTimeoutEvent: {e}", exc_info=True)
            await self._publish_result_failed(event.execution_id, str(e))

    async def _publish_result_stored(self, result: ExecutionResultDomain) -> None:
        """Publish result stored event."""

        size_bytes = len(result.stdout) + len(result.stderr)
        event = ResultStoredEvent(
            execution_id=result.execution_id,
            storage_path=result.execution_id,
            size_bytes=size_bytes,
            storage_type=StorageType.DATABASE,
            metadata=EventMetadata(
                service_name=GroupId.RESULT_PROCESSOR,
                service_version="1.0.0",
            ),
        )

        await self._producer.produce(event_to_produce=event, key=result.execution_id)

    async def _publish_result_failed(self, execution_id: str, error_message: str) -> None:
        """Publish result processing failed event."""

        event = ResultFailedEvent(
            execution_id=execution_id,
            error=error_message,
            metadata=EventMetadata(
                service_name=GroupId.RESULT_PROCESSOR,
                service_version="1.0.0",
            ),
        )

        await self._producer.produce(event_to_produce=event, key=execution_id)

    async def get_status(self) -> dict[str, Any]:
        """Get processor status."""
        return {
            "state": self._state.value,
            "consumer_active": self._consumer is not None,
        }


async def run_result_processor() -> None:
    from contextlib import AsyncExitStack

    container = create_result_processor_container()
    producer = await container.get(UnifiedProducer)
    idempotency_manager = await container.get(IdempotencyManager)
    execution_repo = await container.get(ExecutionRepository)

    processor = ResultProcessor(
        execution_repo=execution_repo,
        producer=producer,
        idempotency_manager=idempotency_manager,
    )

    async with AsyncExitStack() as stack:
        await stack.enter_async_context(processor)
        stack.push_async_callback(container.close)

        while True:
            await asyncio.sleep(60)
            status = await processor.get_status()
            logger.info(f"ResultProcessor status: {status}")
