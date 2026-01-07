from collections.abc import Callable

import pytest
from app.db.repositories import EventRepository
from app.domain.enums.events import EventType
from app.domain.enums.execution import ExecutionStatus
from app.services.kafka_event_service import KafkaEventService
from dishka import AsyncContainer

pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.mongodb]


@pytest.mark.asyncio
async def test_publish_user_registered_event(scope: AsyncContainer, unique_id: Callable[[str], str]) -> None:
    svc: KafkaEventService = await scope.get(KafkaEventService)
    repo: EventRepository = await scope.get(EventRepository)

    user_id = unique_id("user-")
    event_id = await svc.publish_event(
        event_type=EventType.USER_REGISTERED,
        payload={"user_id": user_id, "username": "alice", "email": "alice@example.com"},
        aggregate_id=user_id,
    )
    assert isinstance(event_id, str) and event_id
    stored = await repo.get_event(event_id)
    assert stored is not None and stored.event_id == event_id


@pytest.mark.asyncio
async def test_publish_execution_event(scope: AsyncContainer, unique_id: Callable[[str], str]) -> None:
    svc: KafkaEventService = await scope.get(KafkaEventService)
    repo: EventRepository = await scope.get(EventRepository)

    execution_id = unique_id("exec-")
    event_id = await svc.publish_execution_event(
        event_type=EventType.EXECUTION_QUEUED,
        execution_id=execution_id,
        status=ExecutionStatus.QUEUED,
        metadata=None,
        error_message=None,
    )
    assert isinstance(event_id, str) and event_id
    assert await repo.get_event(event_id) is not None


@pytest.mark.asyncio
async def test_publish_pod_event_and_without_metadata(scope: AsyncContainer, unique_id: Callable[[str], str]) -> None:
    svc: KafkaEventService = await scope.get(KafkaEventService)
    repo: EventRepository = await scope.get(EventRepository)

    execution_id = unique_id("exec-")
    pod_name = unique_id("executor-")

    # Pod event
    eid = await svc.publish_pod_event(
        event_type=EventType.POD_CREATED,
        pod_name=pod_name,
        execution_id=execution_id,
        namespace="ns",
        status="pending",
        metadata=None,
    )
    assert isinstance(eid, str)
    assert await repo.get_event(eid) is not None

    # Generic event without metadata
    user_id = unique_id("user-")
    eid2 = await svc.publish_event(
        event_type=EventType.USER_LOGGED_IN,
        payload={"user_id": user_id, "login_method": "password"},
        aggregate_id=user_id,
        metadata=None,
    )
    assert isinstance(eid2, str)
    assert await repo.get_event(eid2) is not None
