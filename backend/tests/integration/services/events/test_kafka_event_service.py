import pytest

from app.db.repositories import EventRepository
from app.domain.enums.events import EventType
from app.domain.enums.execution import ExecutionStatus
from app.services.kafka_event_service import KafkaEventService

pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.mongodb]


@pytest.mark.asyncio
async def test_publish_user_registered_event(scope) -> None:  # type: ignore[valid-type]
    svc: KafkaEventService = await scope.get(KafkaEventService)
    repo: EventRepository = await scope.get(EventRepository)

    event_id = await svc.publish_event(
        event_type=EventType.USER_REGISTERED,
        payload={"user_id": "u1", "username": "alice", "email": "alice@example.com"},
        aggregate_id="u1",
    )
    assert isinstance(event_id, str) and event_id
    stored = await repo.get_event(event_id)
    assert stored is not None and stored.event_id == event_id


@pytest.mark.asyncio
async def test_publish_execution_event(scope) -> None:  # type: ignore[valid-type]
    svc: KafkaEventService = await scope.get(KafkaEventService)
    repo: EventRepository = await scope.get(EventRepository)

    event_id = await svc.publish_execution_event(
        event_type=EventType.EXECUTION_QUEUED,
        execution_id="exec1",
        status=ExecutionStatus.QUEUED,
        metadata=None,
        error_message=None,
    )
    assert isinstance(event_id, str) and event_id
    assert await repo.get_event(event_id) is not None


@pytest.mark.asyncio
async def test_publish_pod_event_and_without_metadata(scope) -> None:  # type: ignore[valid-type]
    svc: KafkaEventService = await scope.get(KafkaEventService)
    repo: EventRepository = await scope.get(EventRepository)

    # Pod event
    eid = await svc.publish_pod_event(
        event_type=EventType.POD_CREATED,
        pod_name="executor-pod1",
        execution_id="exec1",
        namespace="ns",
        status="pending",
        metadata=None,
    )
    assert isinstance(eid, str)
    assert await repo.get_event(eid) is not None

    # Generic event without metadata
    eid2 = await svc.publish_event(
        event_type=EventType.USER_LOGGED_IN,
        payload={"user_id": "u2", "login_method": "password"},
        aggregate_id="u2",
        metadata=None,
    )
    assert isinstance(eid2, str)
    assert await repo.get_event(eid2) is not None
