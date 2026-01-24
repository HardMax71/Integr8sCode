import logging

from app.domain.enums.events import EventType
from app.domain.events.typed import DomainEvent
from app.events.core import EventDispatcher

from tests.conftest import make_execution_requested_event

_test_logger = logging.getLogger("test.events.event_dispatcher")


def make_event() -> DomainEvent:
    return make_execution_requested_event(execution_id="e1")


async def _async_noop(_: DomainEvent) -> None:
    return None


def test_register_and_remove_handler() -> None:
    disp = EventDispatcher(logger=_test_logger)

    # Register via direct method
    disp.register_handler(EventType.EXECUTION_REQUESTED, _async_noop)
    assert len(disp.get_handlers(EventType.EXECUTION_REQUESTED)) == 1

    # Remove
    ok = disp.remove_handler(EventType.EXECUTION_REQUESTED, _async_noop)
    assert ok is True
    assert len(disp.get_handlers(EventType.EXECUTION_REQUESTED)) == 0


def test_decorator_registration() -> None:
    disp = EventDispatcher(logger=_test_logger)

    @disp.register(EventType.EXECUTION_REQUESTED)
    async def handler(ev: DomainEvent) -> None:  # noqa: ARG001
        return None

    assert len(disp.get_handlers(EventType.EXECUTION_REQUESTED)) == 1


async def test_dispatch_metrics_processed_and_skipped() -> None:
    disp = EventDispatcher(logger=_test_logger)
    called = {"n": 0}

    @disp.register(EventType.EXECUTION_REQUESTED)
    async def handler(_: DomainEvent) -> None:
        called["n"] += 1

    await disp.dispatch(make_event())
    # Dispatch event with no handlers (different type)
    # Reuse base event but fake type by replacing value
    e = make_event()
    e.event_type = EventType.EXECUTION_FAILED
    await disp.dispatch(e)

    metrics = disp.get_metrics()
    assert called["n"] == 1
    assert metrics[EventType.EXECUTION_REQUESTED]["processed"] >= 1
    assert metrics[EventType.EXECUTION_FAILED]["skipped"] >= 1
