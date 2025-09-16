import asyncio
import pytest

from app.domain.enums.events import EventType
from app.domain.enums.saga import SagaState
from app.domain.saga.models import Saga, SagaConfig
from app.services.saga.base_saga import BaseSaga
from app.services.saga.saga_orchestrator import SagaOrchestrator
from app.services.saga.saga_step import CompensationStep, SagaContext, SagaStep


pytestmark = pytest.mark.unit


class _Evt:
    def __init__(self, et: EventType, execution_id: str):
        self.event_type = et
        self.execution_id = execution_id
        self.event_id = "evid"


class _FakeRepo:
    def __init__(self) -> None:
        self.sagas: dict[str, Saga] = {}
        self.saved: list[Saga] = []
        self.existing: dict[tuple[str, str], Saga] = {}

    async def get_saga_by_execution_and_name(self, execution_id: str, saga_name: str):  # noqa: ARG002
        return self.existing.get((execution_id, saga_name))

    async def upsert_saga(self, saga: Saga) -> bool:
        self.sagas[saga.saga_id] = saga
        self.saved.append(saga)
        return True

    async def get_saga(self, saga_id: str) -> Saga | None:
        return self.sagas.get(saga_id)

    async def get_sagas_by_execution(self, execution_id: str):  # noqa: ARG002
        return list(self.sagas.values())


class _FakeProducer:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def produce(self, event_to_produce, key=None):  # noqa: ARG002
        self.events.append(event_to_produce)


class _FakeIdem:
    async def close(self):
        return None


class _FakeEventStore: ...


class _FakeAllocRepo: ...


class _Comp(CompensationStep):
    def __init__(self) -> None:
        super().__init__("comp")
        self.called = False

    async def compensate(self, context: SagaContext) -> bool:  # noqa: ARG002
        self.called = True
        return True


class _StepOK(SagaStep[_Evt]):
    def __init__(self, comp: CompensationStep | None = None) -> None:
        super().__init__("ok")
        self._comp = comp

    async def execute(self, context: SagaContext, event: _Evt) -> bool:  # noqa: ARG002
        return True

    def get_compensation(self) -> CompensationStep | None:
        return self._comp


class _StepFail(SagaStep[_Evt]):
    def __init__(self) -> None:
        super().__init__("fail")

    async def execute(self, context: SagaContext, event: _Evt) -> bool:  # noqa: ARG002
        return False

    def get_compensation(self) -> CompensationStep | None:
        return None


class _StepRaise(SagaStep[_Evt]):
    def __init__(self) -> None:
        super().__init__("raise")

    async def execute(self, context: SagaContext, event: _Evt) -> bool:  # noqa: ARG002
        raise RuntimeError("boom")

    def get_compensation(self) -> CompensationStep | None:
        return None


class _DummySaga(BaseSaga):
    def __init__(self, steps):
        self._steps = steps

    @classmethod
    def get_name(cls) -> str:
        return "dummy"

    @classmethod
    def get_trigger_events(cls) -> list[EventType]:
        return [EventType.EXECUTION_REQUESTED]

    def get_steps(self) -> list[SagaStep]:
        return self._steps


def _orch(repo: _FakeRepo, prod: _FakeProducer) -> SagaOrchestrator:
    cfg = SagaConfig(name="t", enable_compensation=True, store_events=True, publish_commands=False)
    return SagaOrchestrator(
        config=cfg,
        saga_repository=repo,
        producer=prod,
        event_store=_FakeEventStore(),
        idempotency_manager=_FakeIdem(),
        resource_allocation_repository=_FakeAllocRepo(),
    )


@pytest.mark.asyncio
async def test_execute_saga_success_flow() -> None:
    repo = _FakeRepo()
    prod = _FakeProducer()
    orch = _orch(repo, prod)

    # Create a custom saga class with specific steps
    class TestSaga(_DummySaga):
        def __init__(self):
            super().__init__([_StepOK(), _StepOK()])

    orch.register_saga(TestSaga)  # type: ignore[arg-type]
    orch._running = True

    await orch._handle_event(_Evt(EventType.EXECUTION_REQUESTED, "exec-1"))
    # Allow background task to complete
    await asyncio.sleep(0.05)
    # Find last saved saga
    assert repo.saved, "no saga saved"
    last = repo.saved[-1]
    assert last.state == SagaState.COMPLETED and "ok" in last.completed_steps


@pytest.mark.asyncio
async def test_execute_saga_failure_and_compensation() -> None:
    repo = _FakeRepo()
    prod = _FakeProducer()
    orch = _orch(repo, prod)

    comp = _Comp()

    class TestSaga(_DummySaga):
        def __init__(self):
            super().__init__([_StepOK(comp), _StepFail()])

    orch.register_saga(TestSaga)  # type: ignore[arg-type]
    orch._running = True
    await orch._handle_event(_Evt(EventType.EXECUTION_REQUESTED, "exec-2"))
    await asyncio.sleep(0.05)

    # Should have failed and executed compensation
    assert repo.saved[-1].state in (SagaState.FAILED, SagaState.COMPENSATING, SagaState.FAILED)
    assert comp.called is True


@pytest.mark.asyncio
async def test_execute_saga_outer_exception_paths() -> None:
    repo = _FakeRepo()
    prod = _FakeProducer()
    # enable_compensation False to hit _fail_saga in outer except
    cfg = SagaConfig(name="t2", enable_compensation=False, store_events=True, publish_commands=False)
    orch = SagaOrchestrator(cfg, repo, prod, _FakeEventStore(), _FakeIdem(), _FakeAllocRepo())

    class TestSaga(_DummySaga):
        def __init__(self):
            super().__init__([_StepRaise()])

    orch.register_saga(TestSaga)  # type: ignore[arg-type]
    orch._running = True
    await orch._handle_event(_Evt(EventType.EXECUTION_REQUESTED, "ex-err"))
    await asyncio.sleep(0.05)
    # Last saved state is FAILED
    assert repo.saved and repo.saved[-1].state == SagaState.FAILED


@pytest.mark.asyncio
async def test_get_status_and_cancel_publishes_event() -> None:
    repo = _FakeRepo()
    prod = _FakeProducer()
    orch = _orch(repo, prod)
    orch.register_saga(_DummySaga)  # type: ignore[arg-type]
    # Seed one saga
    s = Saga(saga_id="s1", saga_name="dummy", execution_id="e1", state=SagaState.RUNNING)
    s.context_data = {"user_id": "u1"}
    repo.sagas[s.saga_id] = s

    # Cache path
    orch._running_instances[s.saga_id] = s
    got = await orch.get_saga_status("s1")
    assert got is s

    # Cancel it
    ok = await orch.cancel_saga("s1")
    assert ok is True
    # Expect a cancellation event published
    assert prod.events, "no events published on cancel"

    # Compensation branch when already CANCELLED
    s.state = SagaState.CANCELLED
    s.completed_steps = ["ok"]
    await orch.cancel_saga("s1")


@pytest.mark.asyncio
async def test_should_trigger_and_existing_instance_short_circuit() -> None:
    repo = _FakeRepo()
    prod = _FakeProducer()
    orch = _orch(repo, prod)

    class TestSaga(_DummySaga):
        def __init__(self):
            super().__init__([])

    orch.register_saga(TestSaga)  # type: ignore[arg-type]

    # should_trigger
    assert orch._should_trigger_saga(TestSaga, _Evt(EventType.EXECUTION_REQUESTED, "e")) is True
    class _OtherSaga(BaseSaga):
        @classmethod
        def get_name(cls) -> str: return "o"
        @classmethod
        def get_trigger_events(cls) -> list[EventType]: return [EventType.SYSTEM_ERROR]
        def get_steps(self): return []
    assert orch._should_trigger_saga(_OtherSaga, _Evt(EventType.EXECUTION_REQUESTED, "e")) is False

    # existing instance path
    s_existing = Saga(saga_id="sX", saga_name="dummy", execution_id="e", state=SagaState.RUNNING)
    repo.existing[("e", "dummy")] = s_existing
    sid = await orch._start_saga("dummy", _Evt(EventType.EXECUTION_REQUESTED, "e"))
    assert sid == "sX"


@pytest.mark.asyncio
async def test_check_timeouts_marks_saga_and_persists(monkeypatch) -> None:
    repo = _FakeRepo()
    prod = _FakeProducer()
    orch = _orch(repo, prod)
    # Seed a running saga that will be returned as timed out
    s = Saga(saga_id="t1", saga_name="dummy", execution_id="e1", state=SagaState.RUNNING)
    async def fake_find(cutoff):  # noqa: ARG001
        return [s]
    repo.find_timed_out_sagas = fake_find  # type: ignore[attr-defined]

    # Fast sleep to break loop after one iteration
    calls = {"n": 0}
    async def fast_sleep(x):  # noqa: ARG001
        calls["n"] += 1
        orch._running = False
    monkeypatch.setattr("asyncio.sleep", fast_sleep)

    orch._running = True
    await orch._check_timeouts()
    # After one loop, saga should be saved with TIMEOUT
    assert repo.saved and repo.saved[-1].state == SagaState.TIMEOUT


@pytest.mark.asyncio
async def test_start_and_stop_wires_consumer(monkeypatch) -> None:
    repo = _FakeRepo()
    prod = _FakeProducer()
    orch = _orch(repo, prod)

    # Patch mapping to avoid real topics
    monkeypatch.setattr("app.services.saga.saga_orchestrator.get_topic_for_event", lambda et: "t")

    # Fake dispatcher and consumer/wrapper
    class _FD:
        def register_handler(self, *a, **k):
            return None

    class _UC:
        def __init__(self, config=None, event_dispatcher=None):  # noqa: ARG002
            self.started = False
        async def start(self, topics):  # noqa: ARG002
            self.started = True
        async def stop(self):
            self.started = False

    class _Wrapper:
        def __init__(self, consumer, idempotency_manager, dispatcher, **kw):  # noqa: ARG002
            self._c = consumer
        async def start(self, topics):  # noqa: ARG002
            await self._c.start(topics)
        async def stop(self):
            await self._c.stop()

    monkeypatch.setattr("app.services.saga.saga_orchestrator.EventDispatcher", _FD)
    monkeypatch.setattr("app.services.saga.saga_orchestrator.UnifiedConsumer", _UC)
    monkeypatch.setattr("app.services.saga.saga_orchestrator.IdempotentConsumerWrapper", _Wrapper)

    await orch.start()
    assert orch.is_running is True and orch._consumer is not None
    await orch.stop()
    assert orch.is_running is False


@pytest.mark.asyncio
async def test_handle_event_no_trigger() -> None:
    repo = _FakeRepo()
    prod = _FakeProducer()
    orch = _orch(repo, prod)
    # Register a saga that triggers on a different event to ensure no trigger path
    class _Other(BaseSaga):
        @classmethod
        def get_name(cls) -> str: return "o"
        @classmethod
        def get_trigger_events(cls): return [EventType.SYSTEM_ERROR]
        def get_steps(self): return []
    orch.register_saga(_Other)
    orch._running = True
    await orch._handle_event(_Evt(EventType.EXECUTION_REQUESTED, "e"))
    # nothing to assert beyond no exception; covers branch


@pytest.mark.asyncio
async def test_start_saga_edge_cases() -> None:
    repo = _FakeRepo()
    prod = _FakeProducer()
    orch = _orch(repo, prod)

    # Register a dummy saga first
    class TestSaga(_DummySaga):
        def __init__(self):
            super().__init__([])

    orch.register_saga(TestSaga)  # type: ignore[arg-type]

    # Unknown saga name
    with pytest.raises(Exception):
        await orch._start_saga("unknown", _Evt(EventType.EXECUTION_REQUESTED, "e"))
    # Missing execution id
    class _EvtNoExec(_Evt):
        def __init__(self):
            self.event_type = EventType.EXECUTION_REQUESTED
            self.event_id = "id"
            self.execution_id = None
    assert await orch._start_saga("dummy", _EvtNoExec()) is None
