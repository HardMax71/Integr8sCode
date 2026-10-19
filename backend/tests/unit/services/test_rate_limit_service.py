from unittest.mock import AsyncMock

import pytest
import redis.asyncio as redis
import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.services.rate_limit_service import RateLimitService
from app.settings import Settings

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("user_id", ["user-1", "ip:203.0.113.7"])
async def test_redis_failure_lets_the_request_through(
    test_settings: Settings, tracer: trace.Tracer, span_exporter: InMemorySpanExporter, user_id: str
) -> None:
    client = AsyncMock(spec=redis.Redis)
    client.get.side_effect = redis.ConnectionError("Redis is down")
    service = RateLimitService(client, test_settings, tracer, structlog.get_logger("test"))

    status = await service.check_rate_limit(user_id, "/api/v1/execute")

    assert status.allowed is True
    [span] = span_exporter.get_finished_spans()
    assert (span.name, span.attributes) == (
        "rate_limit.request",
        {
            "rate_limit.endpoint": "/api/v1/execute",
            "rate_limit.authenticated": not user_id.startswith("ip:"),
            "rate_limit.algorithm": "redis_error",
        },
    )
