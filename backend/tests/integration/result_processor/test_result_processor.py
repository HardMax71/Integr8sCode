import asyncio
import logging

import pytest
from app.core.database_context import Database
from app.core.metrics import EventMetrics, ExecutionMetrics
from app.db.repositories.execution_repository import ExecutionRepository
from app.domain.enums.events import EventType
from app.domain.enums.execution import ExecutionStatus
from app.domain.enums.kafka import KafkaTopic
from app.domain.events.typed import EventMetadata, ExecutionCompletedEvent, ResultStoredEvent
from app.domain.execution import DomainExecutionCreate
from app.domain.execution.models import ResourceUsageDomain
from app.events.core import ConsumerConfig, UnifiedConsumer, UnifiedProducer
from app.events.core.dispatcher import EventDispatcher
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.services.idempotency import IdempotencyManager
from app.services.result_processor.processor import ResultProcessor
from app.settings import Settings
from dishka import AsyncContainer

# xdist_group: Kafka consumer creation can crash librdkafka when multiple workers
# instantiate Consumer() objects simultaneously. Serial execution prevents this.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.kafka,
    pytest.mark.mongodb,
    pytest.mark.xdist_group("kafka_consumers"),
]

_test_logger = logging.getLogger("test.result_processor.processor")


@pytest.mark.asyncio
async def test_result_processor_persists_and_emits(
    scope: AsyncContainer,
    schema_registry: SchemaRegistryManager,
    event_metrics: EventMetrics,
    consumer_config: ConsumerConfig,
    test_settings: Settings,
) -> None:
    # Ensure schemas
    execution_metrics: ExecutionMetrics = await scope.get(ExecutionMetrics)
    await initialize_event_schemas(schema_registry)

    # Dependencies
    db: Database = await scope.get(Database)
    repo: ExecutionRepository = await scope.get(ExecutionRepository)
    producer: UnifiedProducer = await scope.get(UnifiedProducer)
    idem: IdempotencyManager = await scope.get(IdempotencyManager)

    # Create a base execution to satisfy ResultProcessor lookup
    created = await repo.create_execution(DomainExecutionCreate(
        script="print('x')",
        user_id="u1",
        lang="python",
        lang_version="3.11",
        status=ExecutionStatus.RUNNING,
    ))
    execution_id = created.execution_id

    # Build and start the processor
    processor = ResultProcessor(
        execution_repo=repo,
        producer=producer,
        schema_registry=schema_registry,
        settings=test_settings,
        idempotency_manager=idem,
        logger=_test_logger,
        execution_metrics=execution_metrics,
        event_metrics=event_metrics,
    )

    # Setup a small consumer to capture ResultStoredEvent
    dispatcher = EventDispatcher(logger=_test_logger)
    stored_received = asyncio.Event()

    @dispatcher.register(EventType.RESULT_STORED)
    async def _stored(event: ResultStoredEvent) -> None:
        if event.execution_id == execution_id:
            stored_received.set()

    stored_consumer = UnifiedConsumer(
        consumer_config,
        dispatcher,
        schema_registry=schema_registry,
        settings=test_settings,
        logger=_test_logger,
        event_metrics=event_metrics,
    )

    # Produce the event BEFORE starting consumers (auto_offset_reset="earliest" will read it)
    usage = ResourceUsageDomain(
        execution_time_wall_seconds=0.5,
        cpu_time_jiffies=100,
        clk_tck_hertz=100,
        peak_memory_kb=1024,
    )
    evt = ExecutionCompletedEvent(
        execution_id=execution_id,
        exit_code=0,
        stdout="hello",
        stderr="",
        resource_usage=usage,
        metadata=EventMetadata(service_name="tests", service_version="1.0.0"),
    )
    await producer.produce(evt, key=execution_id)

    # Start consumers after producing
    await stored_consumer.start([KafkaTopic.EXECUTION_RESULTS])

    try:
        async with processor:
            # Await the ResultStoredEvent - signals that processing is complete
            await asyncio.wait_for(stored_received.wait(), timeout=12.0)

            # Now verify DB persistence - should be done since event was emitted
            doc = await db.get_collection("executions").find_one({"execution_id": execution_id})
            assert doc is not None, f"Execution {execution_id} not found in DB after ResultStoredEvent"
            assert doc.get("status") == ExecutionStatus.COMPLETED, (
                f"Expected COMPLETED status, got {doc.get('status')}"
            )
    finally:
        await stored_consumer.stop()
