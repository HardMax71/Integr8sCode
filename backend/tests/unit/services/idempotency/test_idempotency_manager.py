import logging
from unittest.mock import MagicMock

import pytest
from app.core.metrics import DatabaseMetrics
from app.domain.events.typed import BaseEvent
from app.domain.idempotency import KeyStrategy
from app.services.idempotency.idempotency_manager import (
    IdempotencyConfig,
    IdempotencyManager,
)

pytestmark = pytest.mark.unit

# Test logger
_test_logger = logging.getLogger("test.idempotency_manager")


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


def test_manager_generate_key_variants(database_metrics: DatabaseMetrics) -> None:
    repo = MagicMock()
    mgr = IdempotencyManager(IdempotencyConfig(), repo, _test_logger, database_metrics=database_metrics)
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
