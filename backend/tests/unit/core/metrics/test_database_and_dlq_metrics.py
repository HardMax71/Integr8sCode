from unittest.mock import MagicMock

import pytest
import redis

from app.core.metrics import IdempotencyMetrics
from app.settings import Settings

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("keys", "error", "expected"),
    [
        (["idempotency:a", "idempotency:b", "idempotency:c"], None, [3]),
        ([], None, [0]),
        ([], redis.ConnectionError("down"), []),
    ],
)
async def test_idempotency_active_keys_gauge_counts_redis_keys(
    test_settings: Settings, keys: list[str], error: redis.RedisError | None, expected: list[int]
) -> None:
    m = IdempotencyMetrics(test_settings)
    m._redis = MagicMock(spec=redis.Redis)
    m._redis.scan_iter.return_value = iter(keys)
    m._redis.scan_iter.side_effect = error

    observations = m._observe_active_keys(MagicMock())

    assert [o.value for o in observations] == expected
    m._redis.scan_iter.assert_called_once_with(match="idempotency:*", count=1000)
