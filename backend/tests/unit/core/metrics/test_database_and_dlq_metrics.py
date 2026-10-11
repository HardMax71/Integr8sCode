from unittest.mock import MagicMock

import pytest
import redis

from app.core.metrics import DLQMetrics, IdempotencyMetrics
from app.settings import Settings

pytestmark = pytest.mark.unit


def test_idempotency_metrics_methods(test_settings: Settings) -> None:
    """Test IdempotencyMetrics methods with no-op metrics."""
    m = IdempotencyMetrics(test_settings)
    m.record_idempotency_cache_hit("etype", "check")
    m.record_idempotency_cache_miss("etype", "check")
    m.record_idempotency_duplicate_blocked("etype")
    m.record_idempotency_check_duration(0.4, "check_and_reserve")
    m.record_idempotent_processing_duration(0.5, "etype", "completed")


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


def test_dlq_metrics_methods(test_settings: Settings) -> None:
    """Test DLQMetrics methods with no-op metrics."""
    m = DLQMetrics(test_settings)
    m.record_dlq_message_received("topic", "etype")
    m.record_dlq_message_retried("topic", "etype", "success")
    m.record_dlq_message_discarded("topic", "etype", "bad")
    m.record_dlq_processing_duration(0.1, "parse")
    m.update_dlq_queue_size("topic", 10)
    m.update_dlq_queue_size("topic", 7)
    m.record_dlq_message_age(5.0)
    m.record_dlq_processing_error("topic", "etype", "err")
