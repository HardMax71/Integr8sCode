import asyncio
import uuid
from collections.abc import Callable

import pytest
import pytest_asyncio
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


@pytest_asyncio.fixture
async def created_execution(
    test_user: AsyncClient, simple_execution_request: ExecutionRequest
) -> ExecutionResponse:
    """Execution created by test_user (does NOT wait for completion)."""
    resp = await test_user.post(
        "/api/v1/execute", json=simple_execution_request.model_dump()
    )
    assert resp.status_code == 200
    return ExecutionResponse.model_validate(resp.json())


@pytest_asyncio.fixture
async def created_execution_admin(
    test_admin: AsyncClient, simple_execution_request: ExecutionRequest
) -> ExecutionResponse:
    """Execution created by test_admin."""
    resp = await test_admin.post(
        "/api/v1/execute", json=simple_execution_request.model_dump()
    )
    assert resp.status_code == 200
    return ExecutionResponse.model_validate(resp.json())


@pytest_asyncio.fixture
async def execution_with_saga(
    redis_client: redis.Redis,
    created_execution: ExecutionResponse,
) -> tuple[ExecutionResponse, SagaStatusResponse]:
    """Execution with saga guaranteed in MongoDB (via POD_CREATED event).

    POD_CREATED arrives after the saga orchestrator has persisted the saga
    document and dispatched the create-pod command.  We query Beanie directly
    (same DB, no HTTP round-trip) for a deterministic, sleep-free lookup.
    """
    await wait_for_pod_created(redis_client, created_execution.execution_id)

    doc = await SagaDocument.find_one(SagaDocument.execution_id == created_execution.execution_id)
    assert doc is not None, (
        f"No saga document for {created_execution.execution_id} despite POD_CREATED received"
    )

    saga = SagaStatusResponse.model_validate(doc, from_attributes=True)
    assert saga.execution_id == created_execution.execution_id
    return created_execution, saga


@pytest_asyncio.fixture
async def execution_with_notification(
    test_user: AsyncClient,
    redis_client: redis.Redis,
    created_execution: ExecutionResponse,
) -> tuple[ExecutionResponse, NotificationResponse]:
    """Execution with notification guaranteed in MongoDB.

    The notification handler finishes before the result processor publishes
    RESULT_STORED.  Waiting for RESULT_STORED guarantees the notification
    document is in MongoDB.
    """
    await wait_for_result(redis_client, created_execution.execution_id)
    resp = await test_user.get("/api/v1/notifications", params={"limit": 10})
    assert resp.status_code == 200
    result = NotificationListResponse.model_validate(resp.json())
    assert result.notifications, "No notification after execution result stored"
    notification = result.notifications[0]
    assert created_execution.execution_id in (notification.subject + " ".join(notification.tags))
    return created_execution, notification
