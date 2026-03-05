import asyncio
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import redis.asyncio as redis
import structlog
from app.core.metrics import ConnectionMetrics
from app.domain.enums import EventType
from app.domain.sse import SSEExecutionEventData
from app.services.sse import SSEService
from app.services.sse.sse_service import _exec_adapter
from app.settings import Settings

pytestmark = [pytest.mark.e2e, pytest.mark.redis]

_test_logger = structlog.get_logger("test.services.sse.partitioned_event_router_integration")


class _FakeExecRepo:
    async def get_execution(self, execution_id: str) -> None:  # noqa: ARG002
        return None

    async def get_execution_result(self, execution_id: str) -> None:  # noqa: ARG002
        return None


@pytest.mark.asyncio
async def test_service_routes_event_to_redis_stream(redis_client: redis.Redis, test_settings: Settings) -> None:
    suffix = uuid4().hex[:6]
    svc = SSEService(
        redis_client=redis_client,
        execution_repository=_FakeExecRepo(),  # type: ignore[arg-type]
        logger=_test_logger,
        connection_metrics=MagicMock(spec=ConnectionMetrics),
        exec_prefix=f"sse:exec:{suffix}:",
        notif_prefix=f"sse:notif:{suffix}:",
        poll_interval=0.05,
    )

    execution_id = f"e-{uuid4().hex[:8]}"
    ev = SSEExecutionEventData(
        event_type=EventType.EXECUTION_REQUESTED,
        execution_id=execution_id,
    )

    await svc.publish_event(execution_id, ev)

    # Read back from stream
    gen = svc._poll_stream(f"sse:exec:{suffix}:{execution_id}", _exec_adapter)
    msg = await asyncio.wait_for(gen.__anext__(), timeout=2.0)

    assert msg is not None
    assert msg.event_type == ev.event_type
