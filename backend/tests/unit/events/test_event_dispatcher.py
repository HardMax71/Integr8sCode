from app.domain.enums.events import EventType
from app.events.core import EventDispatcher
from app.infrastructure.kafka.events.base import BaseEvent
from tests.helpers import make_execution_requested_event


def make_event():
    return make_execution_requested_event(execution_id="e1")


async def _async_noop(_: BaseEvent) -> None:
    return None


def test_register_and_remove_handler() -> None:
    disp = EventDispatcher()

    # Register via direct method
    disp.register_handler(EventType.EXECUTION_REQUESTED, _async_noop)
    assert len(disp.get_handlers(EventType.EXECUTION_REQUESTED)) == 1

    # Remove
    ok = disp.remove_handler(EventType.EXECUTION_REQUESTED, _async_noop)
    assert ok is True
    assert len(disp.get_handlers(EventType.EXECUTION_REQUESTED)) == 0


def test_decorator_registration() -> None:
    disp = EventDispatcher()

    @disp.register(EventType.EXECUTION_REQUESTED)
    async def handler(ev: BaseEvent) -> None:  # noqa: ARG001
        return None

    assert len(disp.get_handlers(EventType.EXECUTION_REQUESTED)) == 1


async def test_dispatch_metrics_processed_and_skipped() -> None:
    disp = EventDispatcher()
    called = {"n": 0}

    @disp.register(EventType.EXECUTION_REQUESTED)
    async def handler(_: BaseEvent) -> None:
        called["n"] += 1

    await disp.dispatch(make_event())
    # Dispatch event with no handlers (different type)
    # Reuse base event but fake type by replacing value
    e = make_event()
    e.event_type = EventType.EXECUTION_FAILED  # type: ignore[attr-defined]
    await disp.dispatch(e)

    metrics = disp.get_metrics()
    assert called["n"] == 1
    assert metrics[EventType.EXECUTION_REQUESTED.value]["processed"] >= 1
    assert metrics[EventType.EXECUTION_FAILED.value]["skipped"] >= 1
