import logging

from app.domain.enums.events import EventType
from app.domain.enums.storage import ExecutionErrorType
from app.events.core import EventDispatcher
from app.infrastructure.kafka.events.base import BaseEvent
from app.infrastructure.kafka.events.execution import ExecutionFailedEvent, ExecutionRequestedEvent
from app.infrastructure.kafka.events.metadata import AvroEventMetadata

from tests.helpers import make_execution_requested_event

_test_logger = logging.getLogger("test.events.event_dispatcher")


def make_requested_event() -> ExecutionRequestedEvent:
    return make_execution_requested_event(execution_id="e1")


def make_failed_event() -> ExecutionFailedEvent:
    return ExecutionFailedEvent(
        execution_id="e1",
        exit_code=1,
        error_type=ExecutionErrorType.SCRIPT_ERROR,
        error_message="Test failure",
        metadata=AvroEventMetadata(service_name="test", service_version="1.0"),
    )


async def _async_noop(_: BaseEvent) -> None:
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
    async def handler(ev: BaseEvent) -> None:  # noqa: ARG001
        return None

    assert len(disp.get_handlers(EventType.EXECUTION_REQUESTED)) == 1


async def test_dispatch_metrics_processed_and_skipped() -> None:
    disp = EventDispatcher(logger=_test_logger)
    called = {"n": 0}

    @disp.register(EventType.EXECUTION_REQUESTED)
    async def handler(_: BaseEvent) -> None:
        called["n"] += 1

    await disp.dispatch(make_requested_event())
    # Dispatch event with no handlers (different type)
    await disp.dispatch(make_failed_event())

    metrics = disp.get_metrics()
    assert called["n"] == 1
    assert metrics[EventType.EXECUTION_REQUESTED.value]["processed"] >= 1
    assert metrics[EventType.EXECUTION_FAILED.value]["skipped"] >= 1
