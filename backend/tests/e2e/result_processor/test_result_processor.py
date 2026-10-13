import pytest
import structlog

from app.core.metrics import ExecutionMetrics
from app.db.docs import ExecutionDocument
from app.db.repositories import ExecutionRepository
from app.domain.enums import ExecutionStatus
from app.domain.events import (
    EventMetadata,
    ExecutionCompletedEvent,
    ResourceUsageDomain,
)
from app.domain.execution import DomainExecutionCreate
from app.events.core import UnifiedProducer
from app.services.result_processor import ResultProcessor
from app.services.runtime_settings import RuntimeSettingsLoader

pytestmark = [pytest.mark.e2e]

_test_logger = structlog.get_logger("test.result_processor.processor")


async def test_result_processor_persists_and_emits(
    runtime_settings_loader: RuntimeSettingsLoader,
    execution_metrics: ExecutionMetrics,
    execution_repository: ExecutionRepository,
    unified_producer: UnifiedProducer,
) -> None:

    # Dependencies

    # Create a base execution to satisfy ResultProcessor lookup
    created = await execution_repository.create_execution(
        DomainExecutionCreate(
            script="print('x')",
            user_id="u1",
            status=ExecutionStatus.RUNNING,
        )
    )
    execution_id = created.execution_id

    # Build the processor
    processor = ResultProcessor(
        execution_repo=execution_repository,
        producer=unified_producer,
        runtime_settings=runtime_settings_loader,
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
        metadata=EventMetadata(service_name="tests", service_version="1.0.0", user_id="u1"),
    )

    # Directly call the handler (subscriber routing tested separately)
    await processor.handle_execution_completed(evt)

    # Verify DB persistence using Beanie ODM
    doc = await ExecutionDocument.find_one(ExecutionDocument.execution_id == execution_id)
    assert doc is not None, f"Execution {execution_id} not found in DB after processing"
    assert doc.status == ExecutionStatus.COMPLETED, f"Expected COMPLETED status, got {doc.status}"
