import asyncio
import uuid

import pytest

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.repositories.saga_repository import SagaRepository
from app.events.core import UnifiedProducer
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from tests.helpers import make_execution_requested_event
from app.services.saga import SagaOrchestrator
from app.services.saga.execution_saga import ExecutionSaga
from tests.helpers.eventually import eventually

pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.mongodb]


@pytest.mark.asyncio
async def test_saga_orchestrator_creates_saga(scope) -> None:  # type: ignore[valid-type]
    db: AsyncIOMotorDatabase = await scope.get(AsyncIOMotorDatabase)
    registry: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    await initialize_event_schemas(registry)

    producer: UnifiedProducer = await scope.get(UnifiedProducer)
    orchestrator: SagaOrchestrator = await scope.get(SagaOrchestrator)
    saga_repo: SagaRepository = await scope.get(SagaRepository)

    # Prepare unique execution
    execution_id = f"exec-{uuid.uuid4().hex[:8]}"
    event = make_execution_requested_event(execution_id=execution_id)

    # Start orchestrator and wait until consumer is running, then publish the trigger event
    async with orchestrator:
        async def _consumer_running() -> None:
            # Ensure the internal consumer has started
            assert getattr(orchestrator, "_consumer", None) is not None
            assert orchestrator._consumer.is_running  # type: ignore[union-attr]

        await eventually(_consumer_running, timeout=3.0, interval=0.1)
        await producer.produce(event_to_produce=event, key=execution_id)

        # Await saga creation in Mongo (event-driven polling)
        saga_name = ExecutionSaga.get_name()

        async def _exists() -> None:
            doc = await saga_repo.get_saga_by_execution_and_name(execution_id, saga_name)
            assert doc is not None and doc.execution_id == execution_id and doc.saga_name == saga_name

        await eventually(_exists, timeout=12.0, interval=0.2)
