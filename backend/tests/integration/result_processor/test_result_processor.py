import asyncio
import logging
import uuid

import pytest
from app.core.database_context import Database
from app.db.repositories.execution_repository import ExecutionRepository
from app.domain.enums.events import EventType
from app.domain.enums.execution import ExecutionStatus
from app.domain.enums.kafka import KafkaTopic
from app.domain.execution import DomainExecutionCreate
from app.domain.execution.models import ResourceUsageDomain
from app.events.core import UnifiedConsumer, UnifiedProducer
from app.events.core.dispatcher import EventDispatcher
from app.events.core.types import ConsumerConfig
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.infrastructure.kafka.events.execution import ExecutionCompletedEvent
from app.infrastructure.kafka.events.metadata import AvroEventMetadata
from app.services.idempotency import IdempotencyManager
from app.services.result_processor.processor import ResultProcessor
from app.settings import Settings

from tests.helpers.eventually import eventually

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
async def test_result_processor_persists_and_emits(scope) -> None:  # type: ignore[valid-type]
    # Ensure schemas
    registry: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    settings: Settings = await scope.get(Settings)
    await initialize_event_schemas(registry)

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
        schema_registry=registry,
        settings=settings,
        idempotency_manager=idem,
        logger=_test_logger,
    )

    # Setup a small consumer to capture ResultStoredEvent
    dispatcher = EventDispatcher(logger=_test_logger)
    stored_received = asyncio.Event()

    @dispatcher.register(EventType.RESULT_STORED)
    async def _stored(_event) -> None:  # noqa: ANN001
        stored_received.set()

    group_id = f"rp-test.{uuid.uuid4().hex[:6]}"
    cconf = ConsumerConfig(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=group_id,
        enable_auto_commit=True,
        auto_offset_reset="earliest",
    )
    stored_consumer = UnifiedConsumer(
        cconf,
        dispatcher,
        schema_registry=registry,
        settings=settings,
        logger=_test_logger,
    )
    await stored_consumer.start([str(KafkaTopic.EXECUTION_RESULTS)])

    try:
        async with processor:
            # Emit a completed event
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
                metadata=AvroEventMetadata(service_name="tests", service_version="1.0.0"),
            )
            await producer.produce(evt, key=execution_id)

            # Wait for DB persistence (event-driven polling)
            async def _persisted() -> None:
                doc = await db.get_collection("executions").find_one({"execution_id": execution_id})
                assert doc is not None
                assert doc.get("status") == ExecutionStatus.COMPLETED.value

            await eventually(_persisted, timeout=12.0, interval=0.2)

            # Wait for result stored event
            await asyncio.wait_for(stored_received.wait(), timeout=10.0)
    finally:
        await stored_consumer.stop()
