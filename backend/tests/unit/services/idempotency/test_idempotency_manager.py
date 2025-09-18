from unittest.mock import MagicMock
import pytest

from app.infrastructure.kafka.events.base import BaseEvent
from app.services.idempotency.idempotency_manager import (
    IdempotencyConfig,
    IdempotencyManager,
    IdempotencyKeyStrategy,
)


pytestmark = pytest.mark.unit


class TestIdempotencyKeyStrategy:
    def test_event_based(self) -> None:
        event = MagicMock(spec=BaseEvent)
        event.event_type = "test.event"
        event.event_id = "event-123"
        key = IdempotencyKeyStrategy.event_based(event)
        assert key == "test.event:event-123"

    def test_content_hash_all_fields(self) -> None:
        event = MagicMock(spec=BaseEvent)
        event.model_dump.return_value = {
            "event_id": "123",
            "event_type": "test",
            "timestamp": "2025-01-01",
            "metadata": {},
            "field1": "value1",
            "field2": "value2",
        }
        key = IdempotencyKeyStrategy.content_hash(event)
        assert isinstance(key, str) and len(key) == 64

    def test_content_hash_specific_fields(self) -> None:
        event = MagicMock(spec=BaseEvent)
        event.model_dump.return_value = {
            "event_id": "123",
            "event_type": "test",
            "field1": "value1",
            "field2": "value2",
            "field3": "value3",
        }
        key = IdempotencyKeyStrategy.content_hash(event, fields={"field1", "field3"})
        assert isinstance(key, str) and len(key) == 64

    def test_custom(self) -> None:
        event = MagicMock(spec=BaseEvent)
        event.event_type = "test.event"
        key = IdempotencyKeyStrategy.custom(event, "custom-key-123")
        assert key == "test.event:custom-key-123"


class TestIdempotencyConfig:
    def test_default_config(self) -> None:
        config = IdempotencyConfig()
        assert config.key_prefix == "idempotency"
        assert config.default_ttl_seconds == 3600
        assert config.processing_timeout_seconds == 300
        assert config.enable_result_caching is True
        assert config.max_result_size_bytes == 1048576
        assert config.enable_metrics is True
        assert config.collection_name == "idempotency_keys"

    def test_custom_config(self) -> None:
        config = IdempotencyConfig(
            key_prefix="custom",
            default_ttl_seconds=7200,
            processing_timeout_seconds=600,
            enable_result_caching=False,
            max_result_size_bytes=2048,
            enable_metrics=False,
            collection_name="custom_keys",
        )
        assert config.key_prefix == "custom"
        assert config.default_ttl_seconds == 7200
        assert config.processing_timeout_seconds == 600
        assert config.enable_result_caching is False
        assert config.max_result_size_bytes == 2048
        assert config.enable_metrics is False
        assert config.collection_name == "custom_keys"


def test_manager_generate_key_variants() -> None:
    repo = MagicMock()
    mgr = IdempotencyManager(IdempotencyConfig(), repo)
    ev = MagicMock(spec=BaseEvent)
    ev.event_type = "t"
    ev.event_id = "e"
    ev.model_dump.return_value = {"event_id": "e", "event_type": "t"}

    assert mgr._generate_key(ev, "event_based") == "idempotency:t:e"
    ch = mgr._generate_key(ev, "content_hash")
    assert ch.startswith("idempotency:") and len(ch.split(":")[-1]) == 64
    assert mgr._generate_key(ev, "custom", custom_key="k") == "idempotency:t:k"
    with pytest.raises(ValueError):
        mgr._generate_key(ev, "invalid")

