import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator, Callable
from contextlib import suppress

import pytest
import pytest_asyncio
from aiokafka import AIOKafkaConsumer
from app.db.docs.saga import SagaDocument
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.domain.enums.user import UserRole
from app.domain.events.typed import DomainEvent, DomainEventAdapter
from app.schemas_pydantic.execution import ExecutionRequest, ExecutionResponse
from app.schemas_pydantic.notification import NotificationListResponse, NotificationResponse
from app.schemas_pydantic.saga import SagaStatusResponse
from app.schemas_pydantic.saved_script import SavedScriptCreateRequest
from app.schemas_pydantic.user import UserCreate
from app.settings import Settings
from httpx import AsyncClient

_logger = logging.getLogger("test.event_waiter")

# Event types that indicate execution result is stored in MongoDB
RESULT_EVENT_TYPES = frozenset({EventType.RESULT_STORED, EventType.RESULT_FAILED})


class EventWaiter:
    """Async Kafka consumer that resolves futures when matching events arrive.

    Session-scoped: one consumer shared by all tests. Events are buffered so
    a predicate registered after an event was consumed still matches it.
    """

    def __init__(self, bootstrap_servers: str, topics: list[str]) -> None:
        self._waiters: list[tuple[Callable[[DomainEvent], bool], asyncio.Future[DomainEvent]]] = []
        self._buffer: list[DomainEvent] = []
        self._consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=bootstrap_servers,
            group_id=f"test-event-waiter-{uuid.uuid4().hex[:6]}",
            auto_offset_reset="latest",
            enable_auto_commit=True,
        )
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self._consumer.start()
        # Wait for partition assignment so no events are missed
        while not self._consumer.assignment():
            await asyncio.sleep(0.05)
        self._task = asyncio.create_task(self._consume_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        await self._consumer.stop()

    async def _consume_loop(self) -> None:
        async for msg in self._consumer:
            try:
                payload = json.loads(msg.value.decode())
                event = DomainEventAdapter.validate_python(payload)
            except Exception:
                continue
            self._buffer.append(event)
            for predicate, future in list(self._waiters):
                if not future.done() and predicate(event):
                    future.set_result(event)

    async def wait_for(
        self,
        predicate: Callable[[DomainEvent], bool],
        timeout: float = 15.0,
    ) -> DomainEvent:
        """Wait for a Kafka event matching predicate. No polling — pure async."""
        # Check buffer first (event may have arrived before this call)
        for event in self._buffer:
            if predicate(event):
                return event
        # Not in buffer — register waiter and await
        future: asyncio.Future[DomainEvent] = asyncio.get_running_loop().create_future()
        entry = (predicate, future)
        self._waiters.append(entry)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            if entry in self._waiters:
                self._waiters.remove(entry)

    async def wait_for_result(self, execution_id: str, timeout: float = 30.0) -> DomainEvent:
        """Wait for RESULT_STORED or RESULT_FAILED for *execution_id*."""
        return await self.wait_for(
            lambda e: (
                e.event_type in RESULT_EVENT_TYPES
                and getattr(e, "execution_id", None) == execution_id
            ),
            timeout=timeout,
        )

    async def wait_for_saga_command(self, execution_id: str, timeout: float = 15.0) -> DomainEvent:
        """Wait for CREATE_POD_COMMAND — saga is guaranteed in MongoDB after this."""
        return await self.wait_for(
            lambda e: (
                e.event_type == EventType.CREATE_POD_COMMAND
                and getattr(e, "execution_id", None) == execution_id
            ),
            timeout=timeout,
        )


@pytest_asyncio.fixture(scope="session")
async def event_waiter(test_settings: Settings) -> AsyncGenerator[EventWaiter, None]:
    """Session-scoped Kafka event waiter. Starts before any test produces events."""
    prefix = test_settings.KAFKA_TOPIC_PREFIX
    topics = [
        f"{prefix}{KafkaTopic.EXECUTION_EVENTS}",
        f"{prefix}{KafkaTopic.EXECUTION_RESULTS}",
        f"{prefix}{KafkaTopic.SAGA_EVENTS}",
        f"{prefix}{KafkaTopic.SAGA_COMMANDS}",
    ]
    waiter = EventWaiter(test_settings.KAFKA_BOOTSTRAP_SERVERS, topics)
    await waiter.start()
    _logger.info("EventWaiter started on %s", topics)
    yield waiter
    await waiter.stop()


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
    event_waiter: EventWaiter,
    created_execution: ExecutionResponse,
) -> tuple[ExecutionResponse, SagaStatusResponse]:
    """Execution with saga guaranteed in MongoDB (via CREATE_POD_COMMAND event).

    The saga orchestrator persists the saga document multiple times before
    publishing CREATE_POD_COMMAND to Kafka.  Once EventWaiter resolves the
    command, the document is definitively in MongoDB.  We query Beanie
    directly (same DB, no HTTP round-trip) for a deterministic, sleep-free
    lookup.
    """
    await event_waiter.wait_for_saga_command(created_execution.execution_id)

    doc = await SagaDocument.find_one(SagaDocument.execution_id == created_execution.execution_id)
    assert doc is not None, (
        f"No saga document for {created_execution.execution_id} despite CREATE_POD_COMMAND received"
    )

    saga = SagaStatusResponse.model_validate(doc, from_attributes=True)
    assert saga.execution_id == created_execution.execution_id
    return created_execution, saga


@pytest_asyncio.fixture
async def execution_with_notification(
    test_user: AsyncClient,
    event_waiter: EventWaiter,
    created_execution: ExecutionResponse,
) -> tuple[ExecutionResponse, NotificationResponse]:
    """Execution with notification guaranteed in MongoDB.

    Notification handler runs in-process and finishes before the external
    result processor produces RESULT_STORED — so waiting for RESULT_STORED
    guarantees the notification exists.
    """
    await event_waiter.wait_for_result(created_execution.execution_id)
    resp = await test_user.get("/api/v1/notifications", params={"limit": 10})
    assert resp.status_code == 200
    result = NotificationListResponse.model_validate(resp.json())
    assert result.notifications, "No notification despite RESULT_STORED received"
    notification = result.notifications[0]
    assert created_execution.execution_id in (notification.subject + " ".join(notification.tags))
    return created_execution, notification
