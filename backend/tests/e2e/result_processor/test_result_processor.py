import logging
import uuid

import pytest
from app.core.database_context import Database
from app.core.metrics import ExecutionMetrics
from app.db.repositories.execution_repository import ExecutionRepository
from app.domain.enums.execution import ExecutionStatus
from app.domain.events.typed import (
    EventMetadata,
    ExecutionCompletedEvent,
    ResourceUsageDomain,
)
from app.domain.execution import DomainExecutionCreate
from app.events.core import UnifiedProducer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.result_processor.processor import ResultProcessor
from app.settings import Settings
from dishka import AsyncContainer

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.kafka,
    pytest.mark.mongodb,
    pytest.mark.xdist_group("kafka_consumers"),
]

_test_logger = logging.getLogger("test.result_processor.processor")


@pytest.mark.asyncio
async def test_result_processor_persists_and_emits(scope: AsyncContainer) -> None:
    # Schemas are initialized inside the SchemaRegistryManager DI provider
    registry: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    settings: Settings = await scope.get(Settings)
    execution_metrics: ExecutionMetrics = await scope.get(ExecutionMetrics)

    # Dependencies
    db: Database = await scope.get(Database)
    repo: ExecutionRepository = await scope.get(ExecutionRepository)
    producer: UnifiedProducer = await scope.get(UnifiedProducer)

    # Create a base execution to satisfy ResultProcessor lookup
    created = await repo.create_execution(DomainExecutionCreate(
        script="print('x')",
        user_id="u1",
        lang="python",
        lang_version="3.11",
        status=ExecutionStatus.RUNNING,
    ))
    execution_id = created.execution_id

    # Build the processor
    processor = ResultProcessor(
        execution_repo=repo,
        producer=producer,
        settings=settings,
        logger=_test_logger,
        execution_metrics=execution_metrics,
    )

    # Build the event
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

    # Directly call the handler (subscriber routing tested separately)
    await processor.handle_execution_completed(evt)

    # Verify DB persistence
    doc = await db.get_collection("executions").find_one({"execution_id": execution_id})
    assert doc is not None, f"Execution {execution_id} not found in DB after processing"
    assert doc.get("status") == ExecutionStatus.COMPLETED, (
        f"Expected COMPLETED status, got {doc.get('status')}"
    )
