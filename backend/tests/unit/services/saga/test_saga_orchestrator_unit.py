import logging

import pytest
from app.core.metrics import EventMetrics
from app.db.repositories.resource_allocation_repository import ResourceAllocationRepository
from app.db.repositories.saga_repository import SagaRepository
from app.domain.enums.events import EventType
from app.domain.enums.saga import SagaState
from app.domain.events.typed import DomainEvent, ExecutionRequestedEvent
from app.domain.saga.models import Saga, SagaConfig
from app.events.core import UnifiedProducer
from app.services.saga.base_saga import BaseSaga
from app.services.saga.saga_logic import SagaLogic
from app.services.saga.saga_step import CompensationStep, SagaContext, SagaStep

from tests.helpers import make_execution_requested_event

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.services.saga.orchestrator")


class _FakeRepo(SagaRepository):
    """Fake SagaRepository for testing."""

    def __init__(self) -> None:
        self.saved: list[Saga] = []
        self.existing: dict[tuple[str, str], Saga] = {}

    async def get_saga_by_execution_and_name(self, execution_id: str, saga_name: str) -> Saga | None:
        return self.existing.get((execution_id, saga_name))

    async def upsert_saga(self, saga: Saga) -> bool:
        self.saved.append(saga)
        return True


class _FakeProd(UnifiedProducer):
    """Fake UnifiedProducer for testing."""

    def __init__(self) -> None:
        pass  # Skip parent __init__

    async def produce(
        self, event_to_produce: DomainEvent, key: str | None = None, headers: dict[str, str] | None = None
    ) -> None:
        return None


class _FakeAlloc(ResourceAllocationRepository):
    """Fake ResourceAllocationRepository for testing."""

    def __init__(self) -> None:
        pass  # No special attributes needed


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


def _logic(event_metrics: EventMetrics) -> SagaLogic:
    return SagaLogic(
        config=SagaConfig(name="t", enable_compensation=True, store_events=True, publish_commands=False),
        saga_repository=_FakeRepo(),
        producer=_FakeProd(),
        resource_allocation_repository=_FakeAlloc(),
        logger=_test_logger,
        event_metrics=event_metrics,
    )


@pytest.mark.asyncio
async def test_min_success_flow(event_metrics: EventMetrics) -> None:
    logic = _logic(event_metrics)
    logic.register_saga(_Saga)
    # Handle the event
    await logic.handle_event(make_execution_requested_event(execution_id="e"))
    # basic sanity; deep behavior covered by integration
    assert len(logic._sagas) > 0  # noqa: SLF001


@pytest.mark.asyncio
async def test_should_trigger_and_existing_short_circuit(event_metrics: EventMetrics) -> None:
    fake_repo = _FakeRepo()
    logic = SagaLogic(
        config=SagaConfig(name="t", enable_compensation=True, store_events=True, publish_commands=False),
        saga_repository=fake_repo,
        producer=_FakeProd(),
        resource_allocation_repository=_FakeAlloc(),
        logger=_test_logger,
        event_metrics=event_metrics,
    )
    logic.register_saga(_Saga)
    assert logic._should_trigger_saga(_Saga, make_execution_requested_event(execution_id="e")) is True  # noqa: SLF001
    # Existing short-circuit returns existing ID
    s = Saga(saga_id="sX", saga_name="s", execution_id="e", state=SagaState.RUNNING)
    fake_repo.existing[("e", "s")] = s
    sid = await logic._start_saga("s", make_execution_requested_event(execution_id="e"))  # noqa: SLF001
    assert sid == "sX"
