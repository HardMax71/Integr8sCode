import asyncio
import contextlib

import pytest
import redis.asyncio as redis
from fastapi import FastAPI
from httpx2 import AsyncClient

from app.domain.enums import SSEControlEvent
from app.schemas_pydantic.execution import ExecutionRequest, ExecutionResponse
from app.schemas_pydantic.notification import NotificationResponse
from app.schemas_pydantic.sse import SSEExecutionEventSchema
from tests.e2e.conftest import create_execution, streaming_client, wait_for_result

pytestmark = [pytest.mark.e2e]


class TestNotificationStream:
    """Tests for GET /api/v1/events/notifications/stream."""

    @pytest.mark.asyncio
    async def test_notification_stream_unauthenticated(self, client: AsyncClient) -> None:
        """Notification stream requires authentication."""
        response = await client.get("/api/v1/events/notifications/stream")
        assert response.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.kafka
    async def test_notification_stream_delivers_notification(
        self,
        app: FastAPI,
        test_user: AsyncClient,
        exec_request: ExecutionRequest,
        redis_client: redis.Redis,
    ) -> None:
        """A finished execution's notification arrives on the user's stream."""
        me = await test_user.get("/api/v1/auth/me")
        channel = f"sse:notif:{me.json()['user_id']}"

        async with (
            streaming_client(app, test_user) as client,
            client.sse("/api/v1/events/notifications/stream") as source,
        ):
            assert source.response.status_code == 200
            first_event = asyncio.ensure_future(anext(aiter(source)))
            try:
                async with asyncio.timeout(5.0):
                    while (await redis_client.pubsub_numsub(channel))[0][1] == 0:
                        await asyncio.sleep(0.01)

                resp = await test_user.post("/api/v1/execute", json=exec_request.model_dump())
                assert resp.status_code == 200
                execution = ExecutionResponse.model_validate(resp.json())
                await wait_for_result(redis_client, execution.execution_id)

                event = await asyncio.wait_for(first_event, timeout=10.0)
            finally:
                first_event.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await first_event

        assert event.event == "notification"
        notification = NotificationResponse.model_validate_json(event.data)
        assert notification.notification_id
        assert notification.subject


class TestExecutionStream:
    """Tests for GET /api/v1/events/executions/{execution_id}."""

    @pytest.mark.asyncio
    async def test_execution_stream_starts_with_status(
        self, app: FastAPI, test_user: AsyncClient, exec_request: ExecutionRequest
    ) -> None:
        """Execution stream opens with a status event for the execution."""
        execution = await create_execution(test_user, exec_request)

        async with (
            streaming_client(app, test_user) as client,
            client.sse(f"/api/v1/events/executions/{execution.execution_id}") as source,
        ):
            assert source.response.status_code == 200
            assert "text/event-stream" in source.response.headers["content-type"]
            event = await asyncio.wait_for(anext(aiter(source)), timeout=5.0)

        data = SSEExecutionEventSchema.model_validate_json(event.data)
        assert data.event_type == SSEControlEvent.STATUS
        assert data.execution_id == execution.execution_id

    @pytest.mark.asyncio
    async def test_execution_stream_unauthenticated(self, client: AsyncClient) -> None:
        """Execution stream requires authentication."""
        response = await client.get("/api/v1/events/executions/some-id")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_execution_stream_other_users_execution(
        self, test_user: AsyncClient, another_user: AsyncClient, exec_request: ExecutionRequest
    ) -> None:
        """Another user cannot stream a different user's execution."""
        execution = await create_execution(test_user, exec_request)

        response = await another_user.get(f"/api/v1/events/executions/{execution.execution_id}")

        assert response.status_code == 403
        body = response.json()
        assert body["detail"] == "Access denied"
        assert body["status"] == 403
