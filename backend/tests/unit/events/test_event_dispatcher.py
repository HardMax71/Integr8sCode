import logging

from app.domain.enums.events import EventType
from app.domain.events.typed import DomainEvent
from app.events.core import EventDispatcher

from tests.conftest import make_execution_requested_event

_test_logger = logging.getLogger("test.events.event_dispatcher")


def make_event() -> DomainEvent:
    return make_execution_requested_event(execution_id="e1")


def test_decorator_registration() -> None:
    disp = EventDispatcher(logger=_test_logger)

    @disp.register(EventType.EXECUTION_REQUESTED)
    async def handler(ev: DomainEvent) -> None:  # noqa: ARG001
        return None

    assert len(disp._handlers[EventType.EXECUTION_REQUESTED]) == 1


async def test_dispatch_calls_matching_handler() -> None:
    disp = EventDispatcher(logger=_test_logger)
    called = {"n": 0}

    @disp.register(EventType.EXECUTION_REQUESTED)
    async def handler(_: DomainEvent) -> None:
        called["n"] += 1

    await disp.dispatch(make_event())

    # Dispatch event with no handlers (different type) — should be a no-op
    e = make_event()
    e.event_type = EventType.EXECUTION_FAILED
    await disp.dispatch(e)

    assert called["n"] == 1
