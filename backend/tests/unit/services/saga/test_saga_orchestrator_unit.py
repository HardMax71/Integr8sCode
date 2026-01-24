import logging
from unittest.mock import MagicMock

import pytest
from app.core.metrics import EventMetrics
from app.db.repositories.resource_allocation_repository import ResourceAllocationRepository
from app.db.repositories.saga_repository import SagaRepository
from app.domain.enums.events import EventType
from app.domain.enums.saga import SagaState
from app.domain.events.typed import DomainEvent, ExecutionRequestedEvent
from app.domain.saga.models import Saga, SagaConfig
from app.events.core import UnifiedProducer
from app.events.event_store import EventStore
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.idempotency.idempotency_manager import IdempotencyManager
from app.services.saga.base_saga import BaseSaga
from app.services.saga.saga_orchestrator import SagaOrchestrator
from app.services.saga.saga_step import CompensationStep, SagaContext, SagaStep
from app.settings import Settings

from tests.conftest import make_execution_requested_event

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


class _FakeIdem(IdempotencyManager):
    """Fake IdempotencyManager for testing."""

    def __init__(self) -> None:
        pass  # Skip parent __init__

    async def close(self) -> None:
        return None


class _FakeStore(EventStore):
    """Fake EventStore for testing."""

    def __init__(self) -> None:
        pass  # Skip parent __init__


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


def _orch(event_metrics: EventMetrics) -> SagaOrchestrator:
    return SagaOrchestrator(
        config=SagaConfig(name="t", enable_compensation=True, store_events=True, publish_commands=False),
        saga_repository=_FakeRepo(),
        producer=_FakeProd(),
        schema_registry_manager=MagicMock(spec=SchemaRegistryManager),
        settings=MagicMock(spec=Settings),
        event_store=_FakeStore(),
        idempotency_manager=_FakeIdem(),
        resource_allocation_repository=_FakeAlloc(),
        logger=_test_logger,
        event_metrics=event_metrics,
    )


@pytest.mark.asyncio
async def test_min_success_flow(event_metrics: EventMetrics) -> None:
    orch = _orch(event_metrics)
    orch.register_saga(_Saga)
    # Set orchestrator running state via lifecycle property
    orch._lifecycle_started = True
    await orch._handle_event(make_execution_requested_event(execution_id="e"))
    # basic sanity; deep behavior covered by integration
    assert orch.is_running is True


@pytest.mark.asyncio
async def test_should_trigger_and_existing_short_circuit(event_metrics: EventMetrics) -> None:
    fake_repo = _FakeRepo()
    orch = SagaOrchestrator(
        config=SagaConfig(name="t", enable_compensation=True, store_events=True, publish_commands=False),
        saga_repository=fake_repo,
        producer=_FakeProd(),
        schema_registry_manager=MagicMock(spec=SchemaRegistryManager),
        settings=MagicMock(spec=Settings),
        event_store=_FakeStore(),
        idempotency_manager=_FakeIdem(),
        resource_allocation_repository=_FakeAlloc(),
        logger=_test_logger,
        event_metrics=event_metrics,
    )
    orch.register_saga(_Saga)
    assert orch._should_trigger_saga(_Saga, make_execution_requested_event(execution_id="e")) is True
    # Existing short-circuit returns existing ID
    s = Saga(saga_id="sX", saga_name="s", execution_id="e", state=SagaState.RUNNING)
    fake_repo.existing[("e", "s")] = s
    sid = await orch._start_saga("s", make_execution_requested_event(execution_id="e"))
    assert sid == "sX"
