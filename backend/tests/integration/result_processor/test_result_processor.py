import asyncio
import uuid
from tests.helpers.eventually import eventually
import pytest

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.repositories.execution_repository import ExecutionRepository
from app.domain.enums.events import EventType
from app.domain.enums.execution import ExecutionStatus
from app.domain.enums.kafka import KafkaTopic
from app.domain.execution.models import DomainExecution, ResourceUsageDomain
from app.events.core import UnifiedConsumer, UnifiedProducer
from app.events.core.dispatcher import EventDispatcher
from app.events.core.types import ConsumerConfig
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.infrastructure.kafka.events.execution import ExecutionCompletedEvent
from app.infrastructure.kafka.events.metadata import AvroEventMetadata
from app.services.idempotency import IdempotencyManager
from app.services.result_processor.processor import ResultProcessor
from app.settings import get_settings

pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.mongodb]


@pytest.mark.asyncio
async def test_result_processor_persists_and_emits(scope) -> None:  # type: ignore[valid-type]
    # Ensure schemas
    registry: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    await initialize_event_schemas(registry)

    # Dependencies
    db: AsyncIOMotorDatabase = await scope.get(AsyncIOMotorDatabase)
    repo: ExecutionRepository = await scope.get(ExecutionRepository)
    producer: UnifiedProducer = await scope.get(UnifiedProducer)
    idem: IdempotencyManager = await scope.get(IdempotencyManager)

    # Create a base execution to satisfy ResultProcessor lookup
    execution_id = f"exec-{uuid.uuid4().hex[:8]}"
    base = DomainExecution(
        execution_id=execution_id,
        script="print('x')",
        status=ExecutionStatus.RUNNING,
        lang="python",
        lang_version="3.11",
        user_id="u1",
    )
    await repo.create_execution(base)

    # Build and start the processor
    processor = ResultProcessor(
        execution_repo=repo,
        producer=producer,
        idempotency_manager=idem,
    )

    # Setup a small consumer to capture ResultStoredEvent
    settings = get_settings()
    dispatcher = EventDispatcher()
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
    stored_consumer = UnifiedConsumer(cconf, dispatcher)
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
                doc = await db.get_collection("execution_results").find_one({"_id": execution_id})
                assert doc is not None

            await eventually(_persisted, timeout=12.0, interval=0.2)

            # Wait for result stored event
            await asyncio.wait_for(stored_received.wait(), timeout=10.0)
    finally:
        await stored_consumer.stop()
