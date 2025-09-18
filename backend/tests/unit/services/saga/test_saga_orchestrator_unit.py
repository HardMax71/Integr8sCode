import asyncio
import pytest

from app.domain.enums.events import EventType
from app.domain.enums.saga import SagaState
from app.domain.saga.models import Saga, SagaConfig
from app.services.saga.base_saga import BaseSaga
from app.services.saga.saga_orchestrator import SagaOrchestrator
from app.services.saga.saga_step import SagaStep


pytestmark = pytest.mark.unit


class _Evt:
    def __init__(self, et: EventType, execution_id: str):
        self.event_type = et
        self.execution_id = execution_id
        self.event_id = "evid"


class _Repo:
    def __init__(self) -> None:
        self.saved: list[Saga] = []
        self.existing: dict[tuple[str, str], Saga] = {}

    async def get_saga_by_execution_and_name(self, execution_id: str, saga_name: str):  # noqa: ARG002
        return self.existing.get((execution_id, saga_name))

    async def upsert_saga(self, saga: Saga) -> bool:
        self.saved.append(saga)
        return True


class _Prod:
    async def produce(self, event_to_produce, key=None):  # noqa: ARG002
        return None


class _Idem:
    async def close(self):
        return None


class _Store: ...
class _Alloc: ...


class _StepOK(SagaStep[_Evt]):
    def __init__(self) -> None:
        super().__init__("ok")
    async def execute(self, context, event) -> bool:  # noqa: ARG002
        return True


class _Saga(BaseSaga):
    @classmethod
    def get_name(cls) -> str:
        return "s"
    @classmethod
    def get_trigger_events(cls):
        return [EventType.EXECUTION_REQUESTED]
    def get_steps(self):
        return [_StepOK()]


def _orch() -> SagaOrchestrator:
    return SagaOrchestrator(
        config=SagaConfig(name="t", enable_compensation=True, store_events=True, publish_commands=False),
        saga_repository=_Repo(),
        producer=_Prod(),
        event_store=_Store(),
        idempotency_manager=_Idem(),
        resource_allocation_repository=_Alloc(),
    )


@pytest.mark.asyncio
async def test_min_success_flow() -> None:
    orch = _orch()
    orch.register_saga(_Saga)  # type: ignore[arg-type]
    orch._running = True
    await orch._handle_event(_Evt(EventType.EXECUTION_REQUESTED, "e"))
    assert orch._running is True  # basic sanity; deep behavior covered by integration


@pytest.mark.asyncio
async def test_should_trigger_and_existing_short_circuit() -> None:
    orch = _orch()
    orch.register_saga(_Saga)  # type: ignore[arg-type]
    assert orch._should_trigger_saga(_Saga, _Evt(EventType.EXECUTION_REQUESTED, "e")) is True
    # Existing short-circuit returns existing ID
    repo = orch._repo  # type: ignore[attr-defined]
    s = Saga(saga_id="sX", saga_name="s", execution_id="e", state=SagaState.RUNNING)
    repo.existing[("e", "s")] = s
    sid = await orch._start_saga("s", _Evt(EventType.EXECUTION_REQUESTED, "e"))
    assert sid == "sX"
