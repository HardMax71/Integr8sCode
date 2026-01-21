import logging

import pytest
from app.core.metrics import EventMetrics
from app.db.repositories.resource_allocation_repository import ResourceAllocationRepository
from app.db.repositories.saga_repository import SagaRepository
from app.domain.enums.events import EventType
from app.domain.enums.saga import SagaState
from app.domain.events.typed import ExecutionRequestedEvent
from app.domain.saga.models import Saga, SagaConfig
from app.events.core import UnifiedProducer
from app.services.saga.base_saga import BaseSaga
from app.services.saga.saga_logic import SagaLogic
from app.services.saga.saga_step import CompensationStep, SagaContext, SagaStep
from dishka import AsyncContainer

from tests.helpers import make_execution_requested_event

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.services.saga.orchestrator")


class _StepOK(SagaStep[ExecutionRequestedEvent]):
    def __init__(self) -> None:
        super().__init__("ok")

    async def execute(self, context: SagaContext, event: ExecutionRequestedEvent) -> bool:
        return True

    def get_compensation(self) -> CompensationStep | None:
        return None


class _Saga(BaseSaga):
    @classmethod
    def get_name(cls) -> str:
        return "s"

    @classmethod
    def get_trigger_events(cls) -> list[EventType]:
        return [EventType.EXECUTION_REQUESTED]

    def get_steps(self) -> list[SagaStep[ExecutionRequestedEvent]]:
        return [_StepOK()]


@pytest.mark.asyncio
async def test_min_success_flow(
    unit_container: AsyncContainer,
    event_metrics: EventMetrics,
) -> None:
    saga_repo = await unit_container.get(SagaRepository)
    producer = await unit_container.get(UnifiedProducer)
    alloc_repo = await unit_container.get(ResourceAllocationRepository)

    logic = SagaLogic(
        config=SagaConfig(name="t", enable_compensation=True, store_events=True, publish_commands=False),
        saga_repository=saga_repo,
        producer=producer,
        resource_allocation_repository=alloc_repo,
        logger=_test_logger,
        event_metrics=event_metrics,
    )
    logic.register_saga(_Saga)

    await logic.handle_event(make_execution_requested_event(execution_id="e"))

    assert len(logic._sagas) > 0  # noqa: SLF001


@pytest.mark.asyncio
async def test_should_trigger_and_existing_short_circuit(
    unit_container: AsyncContainer,
    event_metrics: EventMetrics,
) -> None:
    saga_repo = await unit_container.get(SagaRepository)
    producer = await unit_container.get(UnifiedProducer)
    alloc_repo = await unit_container.get(ResourceAllocationRepository)

    logic = SagaLogic(
        config=SagaConfig(name="t", enable_compensation=True, store_events=True, publish_commands=False),
        saga_repository=saga_repo,
        producer=producer,
        resource_allocation_repository=alloc_repo,
        logger=_test_logger,
        event_metrics=event_metrics,
    )
    logic.register_saga(_Saga)

    # Use unique execution_id to avoid conflicts with other tests
    exec_id = "test-short-circuit-exec"

    assert logic._should_trigger_saga(_Saga, make_execution_requested_event(execution_id=exec_id)) is True  # noqa: SLF001

    # Create existing saga in real repo
    existing_saga = Saga(saga_id="sX", saga_name="s", execution_id=exec_id, state=SagaState.RUNNING)
    await saga_repo.upsert_saga(existing_saga)

    # Verify it was saved correctly
    found = await saga_repo.get_saga_by_execution_and_name(exec_id, "s")
    assert found is not None, "Saga should be found after upsert"
    assert found.saga_id == "sX"

    # Existing short-circuit returns existing ID
    sid = await logic._start_saga("s", make_execution_requested_event(execution_id=exec_id))  # noqa: SLF001
    assert sid == "sX"
