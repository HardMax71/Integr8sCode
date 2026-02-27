import asyncio
import uuid
from collections.abc import Callable

import pytest
import redis.asyncio as redis
from app.db.docs.saga import SagaDocument
from app.domain.enums import EventType, UserRole
from app.domain.sse import SSEExecutionEventData
from app.schemas_pydantic.execution import ExecutionRequest, ExecutionResponse
from app.schemas_pydantic.notification import NotificationListResponse, NotificationResponse
from app.schemas_pydantic.saga import SagaStatusResponse
from app.schemas_pydantic.saved_script import SavedScriptCreateRequest
from app.schemas_pydantic.user import UserCreate
from httpx import AsyncClient
from pydantic import TypeAdapter

_sse_adapter = TypeAdapter(SSEExecutionEventData)

RESULT_EVENT_TYPES = frozenset({EventType.RESULT_STORED, EventType.RESULT_FAILED})


async def wait_for_sse_event(
    redis_client: redis.Redis,
    execution_id: str,
    predicate: Callable[[SSEExecutionEventData], bool],
    *,
    timeout: float = 15.0,
) -> SSEExecutionEventData:
    """Subscribe to execution's Redis SSE channel and await matching event.

    The SSE bridge publishes all execution lifecycle events to
    sse:exec:{execution_id}. Pure event-driven — no polling.
    """
    channel = f"sse:exec:{execution_id}"
    async with asyncio.timeout(timeout):
        async with redis_client.pubsub(ignore_subscribe_messages=True) as pubsub:
            await pubsub.subscribe(channel)
            async for message in pubsub.listen():
                event = _sse_adapter.validate_json(message["data"])
                if predicate(event):
                    return event
    raise AssertionError("unreachable")


async def wait_for_result(
    redis_client: redis.Redis,
    execution_id: str,
    *,
    timeout: float = 30.0,
) -> SSEExecutionEventData:
    """Wait for RESULT_STORED or RESULT_FAILED."""
    return await wait_for_sse_event(
        redis_client, execution_id,
        lambda e: e.event_type in RESULT_EVENT_TYPES,
        timeout=timeout,
    )


async def wait_for_pod_created(
    redis_client: redis.Redis,
    execution_id: str,
    *,
    timeout: float = 15.0,
) -> SSEExecutionEventData:
    """Wait for POD_CREATED — implies saga started + command dispatched."""
    return await wait_for_sse_event(
        redis_client, execution_id,
        lambda e: e.event_type == EventType.POD_CREATED,
        timeout=timeout,
    )


async def wait_for_notification(
    redis_client: redis.Redis,
    user_id: str,
    *,
    timeout: float = 30.0,
) -> None:
    """Wait for a notification on the user's SSE channel.

    The notification service publishes to sse:notif:{user_id} only after
    persisting to MongoDB, so receiving a message is a correct readiness
    signal — unlike RESULT_STORED which comes from an independent consumer
    group with no ordering guarantee.
    """
    channel = f"sse:notif:{user_id}"
    async with asyncio.timeout(timeout):
        async with redis_client.pubsub(ignore_subscribe_messages=True) as pubsub:
            await pubsub.subscribe(channel)
            async for _message in pubsub.listen():
                return  # first message = notification persisted


@pytest.fixture
def simple_execution_request() -> ExecutionRequest:
    """Simple python print execution."""
    return ExecutionRequest(script="print('test')", lang="python", lang_version="3.11")


@pytest.fixture
def long_running_execution_request() -> ExecutionRequest:
    """30 second sleep execution."""
    return ExecutionRequest(
        script="import time; time.sleep(30); print('done')",
        lang="python",
        lang_version="3.11",
    )


@pytest.fixture
def error_execution_request() -> ExecutionRequest:
    """Execution that raises an error."""
    return ExecutionRequest(
        script="raise ValueError('test error')",
        lang="python",
        lang_version="3.11",
    )


@pytest.fixture
def new_user_request() -> UserCreate:
    """Unique user registration request."""
    uid = uuid.uuid4().hex[:8]
    return UserCreate(
        username=f"user_{uid}",
        email=f"user_{uid}@test.com",
        password="SecurePass123!",
        role=UserRole.USER,
    )


@pytest.fixture
def new_admin_request() -> UserCreate:
    """Unique admin registration request."""
    uid = uuid.uuid4().hex[:8]
    return UserCreate(
        username=f"admin_{uid}",
        email=f"admin_{uid}@test.com",
        password="SecurePass123!",
        role=UserRole.ADMIN,
    )


@pytest.fixture
def new_script_request() -> SavedScriptCreateRequest:
    """Unique saved script request."""
    uid = uuid.uuid4().hex[:8]
    return SavedScriptCreateRequest(
        name=f"Script {uid}",
        script="print('hello')",
        lang="python",
        lang_version="3.11",
    )


async def create_execution(
    client: AsyncClient,
    redis_client: redis.Redis,
    request: ExecutionRequest | None = None,
    *,
    script: str = "print('test')",
    lang: str = "python",
    lang_version: str = "3.11",
) -> ExecutionResponse:
    """POST /execute and return response (does NOT wait for completion)."""
    if request is None:
        request = ExecutionRequest(script=script, lang=lang, lang_version=lang_version)
    resp = await client.post("/api/v1/execute", json=request.model_dump())
    assert resp.status_code == 200
    return ExecutionResponse.model_validate(resp.json())


async def create_execution_with_saga(
    client: AsyncClient,
    redis_client: redis.Redis,
    request: ExecutionRequest | None = None,
    *,
    script: str = "print('test')",
    lang: str = "python",
    lang_version: str = "3.11",
) -> tuple[ExecutionResponse, SagaStatusResponse]:
    """Create execution, wait for POD_CREATED, return (execution, saga).

    POD_CREATED implies the saga orchestrator persisted the document and
    dispatched the create-pod command.
    """
    execution = await create_execution(
        client, redis_client, request, script=script, lang=lang, lang_version=lang_version,
    )
    await wait_for_pod_created(redis_client, execution.execution_id)

    doc = await SagaDocument.find_one(SagaDocument.execution_id == execution.execution_id)
    assert doc is not None, (
        f"No saga document for {execution.execution_id} despite POD_CREATED received"
    )

    saga = SagaStatusResponse.model_validate(doc, from_attributes=True)
    return execution, saga


async def create_execution_with_notification(
    client: AsyncClient,
    redis_client: redis.Redis,
    request: ExecutionRequest | None = None,
    *,
    script: str = "print('test')",
    lang: str = "python",
    lang_version: str = "3.11",
    timeout: float = 30.0,
) -> tuple[ExecutionResponse, NotificationResponse]:
    """Create execution, wait for notification delivery, return (execution, notification).

    Fetches user_id from /auth/me, waits on sse:notif:{user_id} (correct
    signal — notification service publishes after MongoDB persist), then
    queries the notification list.
    """
    me_resp = await client.get("/api/v1/auth/me")
    assert me_resp.status_code == 200
    user_id = me_resp.json()["user_id"]

    execution = await create_execution(
        client, redis_client, request, script=script, lang=lang, lang_version=lang_version,
    )
    await wait_for_notification(redis_client, user_id, timeout=timeout)

    resp = await client.get("/api/v1/notifications", params={"limit": 10})
    assert resp.status_code == 200
    result = NotificationListResponse.model_validate(resp.json())
    assert result.notifications, "No notification after SSE delivery"
    return execution, result.notifications[0]
