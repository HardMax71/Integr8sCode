import asyncio

from app.domain.enums.events import EventType
from app.events.core.dispatcher import EventDispatcher
from app.infrastructure.kafka.events.base import BaseEvent
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.infrastructure.kafka.events.metadata import EventMetadata


def make_event() -> ExecutionRequestedEvent:
    return ExecutionRequestedEvent(
        execution_id="e1",
        script="print(1)",
        language="python",
        language_version="3.11",
        runtime_image="python:3.11-slim",
        runtime_command=["python"],
        runtime_filename="main.py",
        timeout_seconds=30,
        cpu_limit="100m",
        memory_limit="128Mi",
        cpu_request="50m",
        memory_request="64Mi",
        priority=5,
        metadata=EventMetadata(service_name="t", service_version="1"),
    )


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


def test_dispatch_metrics_processed_and_skipped(event_loop) -> None:  # type: ignore[no-redef]
    disp = EventDispatcher()
    called = {"n": 0}

    @disp.register(EventType.EXECUTION_REQUESTED)
    async def handler(_: BaseEvent) -> None:
        called["n"] += 1

    async def run() -> None:
        await disp.dispatch(make_event())
        # Dispatch event with no handlers (different type)
        # Reuse base event but fake type by replacing value
        e = make_event()
        e.event_type = EventType.EXECUTION_FAILED  # type: ignore[attr-defined]
        await disp.dispatch(e)

    event_loop.run_until_complete(run())

    metrics = disp.get_metrics()
    assert called["n"] == 1
    assert metrics[EventType.EXECUTION_REQUESTED.value]["processed"] >= 1
    assert metrics[EventType.EXECUTION_FAILED.value]["skipped"] >= 1

