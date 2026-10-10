from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

from app.core.metrics import IdempotencyMetrics
from app.domain.enums import EventType
from app.domain.events import BaseEvent
from app.domain.idempotency import IdempotencyRecord, IdempotencyStatus, KeyStrategy
from app.services.idempotency import IdempotencyConfig, IdempotencyManager, RedisIdempotencyRepository

pytestmark = pytest.mark.unit

# Test logger
_test_logger = structlog.get_logger("test.idempotency_manager")


class TestIdempotencyConfig:
    def test_default_config(self) -> None:
        config = IdempotencyConfig()
        assert config.key_prefix == "idempotency"
        assert config.default_ttl_seconds == 3600
        assert config.processing_timeout_seconds == 300
        assert config.enable_result_caching is True
        assert config.max_result_size_bytes == 1048576

    def test_custom_config(self) -> None:
        config = IdempotencyConfig(
            key_prefix="custom",
            default_ttl_seconds=7200,
            processing_timeout_seconds=600,
            enable_result_caching=False,
            max_result_size_bytes=2048,
        )
        assert config.key_prefix == "custom"
        assert config.default_ttl_seconds == 7200
        assert config.processing_timeout_seconds == 600
        assert config.enable_result_caching is False
        assert config.max_result_size_bytes == 2048


def test_manager_generate_key_variants(idempotency_metrics: IdempotencyMetrics) -> None:
    repo = MagicMock()
    mgr = IdempotencyManager(IdempotencyConfig(), repo, _test_logger, idempotency_metrics=idempotency_metrics)
    ev = MagicMock(spec=BaseEvent)
    ev.event_type = "t"
    ev.event_id = "e"
    ev.model_dump.return_value = {"event_id": "e", "event_type": "t"}

    assert mgr._generate_key(ev, KeyStrategy.EVENT_BASED) == "idempotency:t:e"
    ch = mgr._generate_key(ev, KeyStrategy.CONTENT_HASH)
    assert ch.startswith("idempotency:") and len(ch.split(":")[-1]) == 64
    assert mgr._generate_key(ev, KeyStrategy.CUSTOM, custom_key="k") == "idempotency:t:k"
    with pytest.raises(ValueError):
        mgr._generate_key(ev, KeyStrategy.CUSTOM)  # CUSTOM requires custom_key


def _event() -> MagicMock:
    ev = MagicMock(spec=BaseEvent)
    ev.event_type = EventType.CREATE_POD_COMMAND
    ev.event_id = "evt-1"
    return ev


def _manager(repo: AsyncMock, metrics: MagicMock) -> IdempotencyManager:
    return IdempotencyManager(IdempotencyConfig(), repo, _test_logger, idempotency_metrics=metrics)


@pytest.mark.parametrize(
    ("method", "kwargs", "expected_status"),
    [
        ("mark_completed", {}, IdempotencyStatus.COMPLETED),
        ("mark_failed", {"error": "boom"}, IdempotencyStatus.FAILED),
        ("mark_completed_with_json", {"cached_json": "{}"}, IdempotencyStatus.COMPLETED),
    ],
)
async def test_marking_records_processing_duration(
    method: str, kwargs: dict[str, str], expected_status: IdempotencyStatus
) -> None:
    repo = AsyncMock(spec=RedisIdempotencyRepository)
    repo.find_by_key.return_value = IdempotencyRecord(
        key="idempotency:create_pod_command:evt-1",
        status=IdempotencyStatus.PROCESSING,
        event_type=EventType.CREATE_POD_COMMAND,
        event_id="evt-1",
        created_at=datetime.now(timezone.utc) - timedelta(seconds=2),
        ttl_seconds=3600,
    )
    repo.update_record.return_value = 1
    metrics = MagicMock(spec=IdempotencyMetrics)

    assert await getattr(_manager(repo, metrics), method)(_event(), **kwargs) is True

    metrics.record_idempotent_processing_duration.assert_called_once()
    duration, event_type, status = metrics.record_idempotent_processing_duration.call_args.args
    assert 2.0 <= duration < 3.0
    assert event_type == EventType.CREATE_POD_COMMAND
    assert status == expected_status


async def test_marking_missing_key_records_nothing() -> None:
    repo = AsyncMock(spec=RedisIdempotencyRepository)
    repo.find_by_key.return_value = None
    metrics = MagicMock(spec=IdempotencyMetrics)

    assert await _manager(repo, metrics).mark_completed(_event()) is False

    metrics.record_idempotent_processing_duration.assert_not_called()
    repo.update_record.assert_not_called()


async def test_check_and_reserve_records_check_duration_only() -> None:
    repo = AsyncMock(spec=RedisIdempotencyRepository)
    repo.find_by_key.return_value = None
    metrics = MagicMock(spec=IdempotencyMetrics)

    result = await _manager(repo, metrics).check_and_reserve(_event())

    assert result.is_duplicate is False
    assert result.status == IdempotencyStatus.PROCESSING
    repo.insert_processing.assert_awaited_once()
    metrics.record_idempotency_cache_miss.assert_called_once_with(EventType.CREATE_POD_COMMAND, "check_and_reserve")
    metrics.record_idempotency_check_duration.assert_called_once()
    assert metrics.record_idempotency_check_duration.call_args.args[1] == "check_and_reserve"
    metrics.record_idempotent_processing_duration.assert_not_called()
