import logging
from typing import Any

import pytest
from app.domain.enums.events import EventType
from app.domain.enums.saga import SagaState
from app.domain.saga.models import Saga, SagaConfig
from app.services.saga.base_saga import BaseSaga
from app.services.saga.saga_orchestrator import SagaOrchestrator
from app.services.saga.saga_step import SagaStep

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.services.saga.orchestrator")


class _Evt:
    def __init__(self, et: EventType, execution_id: str):
        self.event_type = et
        self.execution_id = execution_id
        self.event_id = "evid"


class _Repo:
    def __init__(self) -> None:
        self.saved: list[Saga] = []
        self.existing: dict[tuple[str, str], Saga] = {}

    async def get_saga_by_execution_and_name(self, execution_id: str, saga_name: str) -> Saga | None:  # noqa: ARG002
        return self.existing.get((execution_id, saga_name))

    async def upsert_saga(self, saga: Saga) -> bool:
        self.saved.append(saga)
        return True


class _Prod:
    async def produce(self, event_to_produce: Any, key: str | None = None) -> None:  # noqa: ARG002
        return None


class _Idem:
    async def close(self) -> None:
        return None


class _Store: ...
class _Alloc: ...
class _SchemaRegistry: ...
class _Settings: ...


class _StepOK(SagaStep[Any]):
    def __init__(self) -> None:
        super().__init__("ok")
    async def execute(self, context: Any, event: Any) -> bool:  # noqa: ARG002
        return True
    def get_compensation(self) -> None:
        return None


class _Saga(BaseSaga):
    @classmethod
    def get_name(cls) -> str:
        return "s"
    @classmethod
    def get_trigger_events(cls) -> list[EventType]:
        return [EventType.EXECUTION_REQUESTED]
    def get_steps(self) -> list[SagaStep[Any]]:
        return [_StepOK()]


def _orch() -> SagaOrchestrator:
    return SagaOrchestrator(
        config=SagaConfig(name="t", enable_compensation=True, store_events=True, publish_commands=False),
        saga_repository=_Repo(),  # type: ignore[arg-type]
        producer=_Prod(),  # type: ignore[arg-type]
        schema_registry_manager=_SchemaRegistry(),  # type: ignore[arg-type]
        settings=_Settings(),  # type: ignore[arg-type]
        event_store=_Store(),  # type: ignore[arg-type]
        idempotency_manager=_Idem(),  # type: ignore[arg-type]
        resource_allocation_repository=_Alloc(),  # type: ignore[arg-type]
        logger=_test_logger,
    )


@pytest.mark.asyncio
async def test_min_success_flow() -> None:
    orch = _orch()
    orch.register_saga(_Saga)
    orch._running = True  # type: ignore[attr-defined]
    await orch._handle_event(_Evt(EventType.EXECUTION_REQUESTED, "e"))  # type: ignore[arg-type]
    assert orch._running is True  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_should_trigger_and_existing_short_circuit() -> None:
    orch = _orch()
    orch.register_saga(_Saga)
    assert orch._should_trigger_saga(_Saga, _Evt(EventType.EXECUTION_REQUESTED, "e")) is True  # type: ignore[arg-type]
    # Existing short-circuit returns existing ID
    repo = orch._repo
    s = Saga(saga_id="sX", saga_name="s", execution_id="e", state=SagaState.RUNNING)
    repo.existing[("e", "s")] = s  # type: ignore[attr-defined]
    sid = await orch._start_saga("s", _Evt(EventType.EXECUTION_REQUESTED, "e"))  # type: ignore[arg-type]
    assert sid == "sX"
