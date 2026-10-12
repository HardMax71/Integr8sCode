from unittest.mock import AsyncMock, MagicMock

import pytest
import redis.asyncio as redis
import structlog

from app.core.metrics import RateLimitMetrics
from app.services.rate_limit_service import RateLimitService
from app.settings import Settings

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("user_id", ["user-1", "ip:203.0.113.7"])
async def test_redis_failure_lets_the_request_through(test_settings: Settings, user_id: str) -> None:
    client = AsyncMock(spec=redis.Redis)
    client.get.side_effect = redis.ConnectionError("Redis is down")
    metrics = MagicMock(spec=RateLimitMetrics)
    service = RateLimitService(client, test_settings, metrics, structlog.get_logger("test"))

    status = await service.check_rate_limit(user_id, "/api/v1/execute")

    assert status.allowed is True
    metrics.record_request.assert_called_once_with("/api/v1/execute", not user_id.startswith("ip:"), "redis_error")
