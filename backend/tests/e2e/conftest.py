import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx2
import pytest
import structlog
from beanie.operators import In
from dishka import AsyncContainer
from fastapi import FastAPI
from httpx2 import AsyncClient
from pydantic import SecretStr
from starlette.types import ASGIApp, Message, Scope

from app.core.security import SecurityService
from app.db.docs import EventDocument, ExecutionDocument, NotificationDocument
from app.db.repositories import (
    AdminEventsRepository,
    AdminSettingsRepository,
    DLQRepository,
    EventRepository,
    ExecutionRepository,
    NotificationRepository,
    SavedScriptRepository,
)
from app.domain.enums import EventType, ExecutionStatus, NotificationStatus, UserRole
from app.events import UnifiedProducer
from app.runtime_registry import DEFAULT_LANG
from app.schemas_pydantic.execution import ExecutionRequest, ExecutionResponse
from app.schemas_pydantic.notification import NotificationListResponse, NotificationResponse
from app.schemas_pydantic.saved_script import SavedScriptCreateRequest
from app.schemas_pydantic.user import UserCreate
from app.services.admin import AdminUserService
from app.services.event_service import EventService
from app.services.execution_service import ExecutionService
from app.services.idempotency import IdempotencyManager
from app.services.notification_service import NotificationService
from app.services.runtime_settings import RuntimeSettingsLoader
from app.services.saved_script_service import SavedScriptService
from app.services.sse import SSERedisBus
from app.services.user_settings_service import UserSettingsService


class _Exchange:
    """One request's ASGI side: the body to hand over, the response chunks and the client's disconnect."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.request_sent = False
        self.chunks: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.started: asyncio.Future[Message] = asyncio.get_running_loop().create_future()
        self.disconnect = asyncio.Event()

    async def receive(self) -> Message:
        if not self.request_sent:
            self.request_sent = True
            return {"type": "http.request", "body": self.body, "more_body": False}
        await self.disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            self.started.set_result(message)
        elif message["type"] == "http.response.body":
            await self.chunks.put(message.get("body", b""))
            if not message.get("more_body", False):
                await self.chunks.put(None)

    async def run(self, app: ASGIApp, scope: Scope) -> None:
        await app(scope, self.receive, self.send)

    def end_body(self, _app_task: asyncio.Task[None]) -> None:
        self.chunks.put_nowait(None)


class _QueuedBody(httpx2.AsyncByteStream):
    def __init__(self, exchange: _Exchange, app_task: asyncio.Task[None]) -> None:
        self._exchange = exchange
        self._app_task = app_task

    async def __aiter__(self) -> AsyncIterator[bytes]:
        while (chunk := await self._exchange.chunks.get()) is not None:
            yield chunk
        if self._app_task.done() and not self._app_task.cancelled() and (error := self._app_task.exception()):
            raise error

    async def aclose(self) -> None:
        self._exchange.disconnect.set()
        await asyncio.wait({self._app_task}, timeout=1.0)
        self._app_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._app_task


class StreamingASGITransport(httpx2.AsyncBaseTransport):
    """Returns once response headers arrive; httpx2.ASGITransport waits for the whole body (encode/httpx#2186)."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        exchange = _Exchange(await request.aread())
        scope: Scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": request.method,
            "headers": [(k.lower(), v) for (k, v) in request.headers.raw],
            "scheme": request.url.scheme,
            "path": request.url.path,
            "raw_path": request.url.raw_path.split(b"?")[0],
            "query_string": request.url.query,
            "server": (request.url.host, request.url.port),
            "client": ("127.0.0.1", 123),
            "root_path": "",
        }
        app_task = asyncio.create_task(exchange.run(self._app, scope))
        app_task.add_done_callback(exchange.end_body)
        first: set[asyncio.Future[Any]] = {app_task, exchange.started}
        await asyncio.wait(first, return_when=asyncio.FIRST_COMPLETED)
        if not exchange.started.done():
            app_task.result()
            raise RuntimeError("ASGI app returned without starting a response")
        start = exchange.started.result()
        return httpx2.Response(
            start["status"],
            headers=start.get("headers", []),
            stream=_QueuedBody(exchange, app_task),
            request=request,
        )


def streaming_client(app: FastAPI, user: AsyncClient) -> AsyncClient:
    """Client that streams responses (SSE) with the same session as ``user``."""
    return AsyncClient(
        transport=StreamingASGITransport(app),
        base_url=user.base_url,
        cookies=user.cookies,
        headers=user.headers,
    )


async def wait_for_event(execution_id: str, *event_types: EventType, timeout: float = 30.0) -> None:
    """Wait until the events collection holds one of ``event_types`` for the execution.

    The producer stores every event before it publishes it, so an event that happened before the wait began counts.
    """
    async with asyncio.timeout(timeout):
        while not await EventDocument.find_one(
            EventDocument.execution_id == execution_id, In(EventDocument.event_type, list(event_types))
        ):
            await asyncio.sleep(0.2)


@pytest.fixture
async def notification_service(scope: AsyncContainer) -> NotificationService:
    return await scope.get(NotificationService)


@pytest.fixture
async def user_settings_service(scope: AsyncContainer) -> UserSettingsService:
    return await scope.get(UserSettingsService)


@pytest.fixture
async def execution_service(scope: AsyncContainer) -> ExecutionService:
    return await scope.get(ExecutionService)


@pytest.fixture
async def saved_script_service(scope: AsyncContainer) -> SavedScriptService:
    return await scope.get(SavedScriptService)


@pytest.fixture
async def idempotency_manager(scope: AsyncContainer) -> IdempotencyManager:
    return await scope.get(IdempotencyManager)


@pytest.fixture
async def event_service(scope: AsyncContainer) -> EventService:
    return await scope.get(EventService)


@pytest.fixture
async def admin_user_service(scope: AsyncContainer) -> AdminUserService:
    return await scope.get(AdminUserService)


@pytest.fixture
async def sse_redis_bus(scope: AsyncContainer) -> SSERedisBus:
    return await scope.get(SSERedisBus)


@pytest.fixture
async def runtime_settings_loader(scope: AsyncContainer) -> RuntimeSettingsLoader:
    return await scope.get(RuntimeSettingsLoader)


@pytest.fixture
async def security_service(scope: AsyncContainer) -> SecurityService:
    return await scope.get(SecurityService)


@pytest.fixture
async def unified_producer(scope: AsyncContainer) -> UnifiedProducer:
    return await scope.get(UnifiedProducer)


@pytest.fixture
async def execution_repository(scope: AsyncContainer) -> ExecutionRepository:
    return await scope.get(ExecutionRepository)


@pytest.fixture
async def event_repository(scope: AsyncContainer) -> EventRepository:
    return await scope.get(EventRepository)


@pytest.fixture
async def dlq_repository(scope: AsyncContainer) -> DLQRepository:
    return await scope.get(DLQRepository)


@pytest.fixture
async def saved_script_repository(scope: AsyncContainer) -> SavedScriptRepository:
    return await scope.get(SavedScriptRepository)


@pytest.fixture
async def notification_repository(scope: AsyncContainer) -> NotificationRepository:
    return await scope.get(NotificationRepository)


@pytest.fixture
async def admin_settings_repository(scope: AsyncContainer) -> AdminSettingsRepository:
    return await scope.get(AdminSettingsRepository)


@pytest.fixture
async def admin_events_repository(scope: AsyncContainer) -> AdminEventsRepository:
    return await scope.get(AdminEventsRepository)


@pytest.fixture
def exec_request() -> ExecutionRequest:
    """Simple python print execution."""
    return ExecutionRequest(script="print('test')")


@pytest.fixture
def long_running_execution_request() -> ExecutionRequest:
    """30 second sleep execution."""
    return ExecutionRequest(
        script="import time; time.sleep(30); print('done')",
    )


@pytest.fixture
def error_execution_request() -> ExecutionRequest:
    """Execution that raises an error."""
    return ExecutionRequest(
        script="raise ValueError('test error')",
    )


@pytest.fixture
def new_user_request() -> UserCreate:
    """Unique user registration request."""
    uid = uuid.uuid4().hex[:8]
    return UserCreate(
        username=f"user_{uid}",
        email=f"user_{uid}@test.com",
        password=SecretStr("SecurePass123!"),
        role=UserRole.USER,
    )


@pytest.fixture
def new_admin_request() -> UserCreate:
    """Unique admin registration request."""
    uid = uuid.uuid4().hex[:8]
    return UserCreate(
        username=f"admin_{uid}",
        email=f"admin_{uid}@test.com",
        password=SecretStr("SecurePass123!"),
        role=UserRole.ADMIN,
    )


@pytest.fixture
def new_script_request() -> SavedScriptCreateRequest:
    """Unique saved script request."""
    uid = uuid.uuid4().hex[:8]
    return SavedScriptCreateRequest(
        name=f"Script {uid}",
        script="print('hello')",
    )


async def create_execution(
    client: AsyncClient,
    request: ExecutionRequest,
) -> ExecutionResponse:
    """POST /execute and return response (does NOT wait for completion)."""
    resp = await client.post("/api/v1/execute", json=request.model_dump())
    assert resp.status_code == 200
    return ExecutionResponse.model_validate(resp.json())


async def store_execution(
    client: AsyncClient, *, status: ExecutionStatus = ExecutionStatus.COMPLETED, lang: str = DEFAULT_LANG
) -> str:
    """Insert an execution owned by the client's user straight into MongoDB, for tests that need the row, not a pod."""
    me = await client.get("/api/v1/auth/me")
    repo = ExecutionRepository(structlog.get_logger("tests"))
    created = ExecutionDocument(script="print('stored')", user_id=me.json()["user_id"], status=status, lang=lang)
    await repo.create_execution(created)
    return created.execution_id


async def create_execution_with_notification(
    client: AsyncClient, request: ExecutionRequest
) -> tuple[ExecutionResponse, NotificationResponse]:
    """Create an execution and wait until its notification is delivered, so later status changes don't race it."""
    execution = await create_execution(client, request)
    async with asyncio.timeout(30.0):
        while not (
            doc := await NotificationDocument.find_one(
                In(NotificationDocument.tags, [f"exec:{execution.execution_id}"]),
                NotificationDocument.status == NotificationStatus.DELIVERED,
            )
        ):
            await asyncio.sleep(0.2)

    resp = await client.get("/api/v1/notifications", params={"limit": 100})
    assert resp.status_code == 200
    notifications = NotificationListResponse.model_validate(resp.json()).notifications
    return execution, next(n for n in notifications if n.notification_id == doc.notification_id)
