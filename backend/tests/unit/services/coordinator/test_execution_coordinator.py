import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.domain.enums.kafka import KafkaTopic
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.execution import (
    ExecutionAcceptedEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionRequestedEvent,
)
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.services.coordinator.coordinator import ExecutionCoordinator
from app.services.idempotency import IdempotencyManager
from app.services.coordinator.resource_manager import ResourceAllocation


class DummySchema(SchemaRegistryManager):
    def __init__(self) -> None:  # type: ignore[no-untyped-def]
        pass


class DummyEventStore:
    async def get_execution_events(self, execution_id, types):  # noqa: ANN001
        return []


def make_request_event(execution_id: str = "e-1") -> ExecutionRequestedEvent:
    return ExecutionRequestedEvent(
        execution_id=execution_id,
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


def make_coordinator() -> ExecutionCoordinator:
    producer = SimpleNamespace(produce=AsyncMock())
    # Minimal fakes for required deps
    class FakeIdem(IdempotencyManager):  # type: ignore[misc]
        def __init__(self, *_: object, **__: object) -> None:  # noqa: D401
            pass
        async def initialize(self) -> None:  # noqa: D401
            return None

    class FakeRepo:
        async def get_execution(self, *_: object, **__: object):  # noqa: D401, ANN001
            return None

    coord = ExecutionCoordinator(
        producer=producer,  # type: ignore[arg-type]
        schema_registry_manager=DummySchema(),
        event_store=DummyEventStore(),
        execution_repository=FakeRepo(),  # type: ignore[arg-type]
        idempotency_manager=FakeIdem(None),  # type: ignore[arg-type]
        max_concurrent_scheduling=2,
        scheduling_interval_seconds=0.01,
    )
    return coord


@pytest.mark.asyncio
async def test_handle_execution_requested_accepts_and_publishes() -> None:
    coord = make_coordinator()
    # Spy on publish call
    coord._publish_execution_accepted = AsyncMock()  # type: ignore[attr-defined]

    ev = make_request_event("acc-1")
    await coord._handle_execution_requested(ev)

    coord._publish_execution_accepted.assert_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_handle_execution_requested_queue_full_path() -> None:
    coord = make_coordinator()
    # Force queue full
    async def fake_add(*args, **kwargs):  # noqa: ANN001, ANN201
        return False, None, "Queue is full"

    coord.queue_manager.add_execution = AsyncMock(side_effect=fake_add)  # type: ignore[assignment]
    coord._publish_queue_full = AsyncMock()  # type: ignore[attr-defined]

    ev = make_request_event("full-1")
    await coord._handle_execution_requested(ev)

    coord._publish_queue_full.assert_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_publish_queue_full_produces_failed_event() -> None:
    coord = make_coordinator()
    ev = make_request_event("full-2")

    await coord._publish_queue_full(ev, "Queue is full")
    # Verify producer called with ExecutionFailedEvent
    call = coord.producer.produce.call_args  # type: ignore[attr-defined]
    assert isinstance(call.kwargs["event_to_produce"], ExecutionFailedEvent)
    assert call.kwargs["key"] == ev.execution_id


@pytest.mark.asyncio
async def test_publish_execution_accepted_produces_event() -> None:
    coord = make_coordinator()
    ev = make_request_event("acc-2")
    await coord._publish_execution_accepted(ev, position=3, priority=5)
    call = coord.producer.produce.call_args  # type: ignore[attr-defined]
    assert isinstance(call.kwargs["event_to_produce"], ExecutionAcceptedEvent)


@pytest.mark.asyncio
async def test_route_execution_event_branches() -> None:
    coord = make_coordinator()
    # Should route requested
    await coord._route_execution_event(make_request_event("r1"))
    # Result routing path
    from app.domain.execution.models import ResourceUsageDomain
    completed = ExecutionCompletedEvent(
        execution_id="r1",
        stdout="",
        stderr="",
        exit_code=0,
        resource_usage=ResourceUsageDomain.from_dict({}),
        metadata=EventMetadata(service_name="t", service_version="1"),
    )
    await coord._route_execution_result(completed)

    status = await coord.get_status()
    assert isinstance(status, dict)


@pytest.mark.asyncio
async def test_publish_scheduling_failed_and_build_metadata(monkeypatch) -> None:
    coord = make_coordinator()
    # Patch execution repository for _build_command_metadata
    from app.domain.execution.models import DomainExecution
    class R:
        async def get_execution(self, *_: object, **__: object) -> DomainExecution:  # noqa: ANN001
            return DomainExecution(script="print(1)", lang="python", lang_version="3.11", user_id="u-db")
    coord.execution_repository = R()  # type: ignore[assignment]
    # Call _publish_scheduling_failed to produce ExecutionFailedEvent
    ev = make_request_event("sf-1")
    await coord._publish_scheduling_failed(ev, "no resources")
    call = coord.producer.produce.call_args  # type: ignore[attr-defined]
    assert isinstance(call.kwargs["event_to_produce"], ExecutionFailedEvent)



@pytest.mark.asyncio
async def test_schedule_execution_requeues_on_no_resources() -> None:
    coord = make_coordinator()
    coord.resource_manager.request_allocation = AsyncMock(return_value=None)  # type: ignore[assignment]
    coord.queue_manager.requeue_execution = AsyncMock()  # type: ignore[attr-defined]

    ev = make_request_event("rq-1")
    await coord._schedule_execution(ev)

    coord.queue_manager.requeue_execution.assert_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_schedule_execution_success_publishes_started() -> None:
    coord = make_coordinator()
    # Make allocation available
    coord.resource_manager.request_allocation = AsyncMock(
        return_value=ResourceAllocation(cpu_cores=0.5, memory_mb=256)
    )  # type: ignore[assignment]
    # Avoid DB path in _publish_execution_started
    coord._publish_execution_started = AsyncMock()  # type: ignore[attr-defined]

    ev = make_request_event("ok-1")
    await coord._schedule_execution(ev)

    coord._publish_execution_started.assert_awaited()  # type: ignore[attr-defined]
    assert "ok-1" in coord._active_executions
