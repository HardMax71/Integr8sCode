import json
import logging

import pytest
from app.events.core import ProducerMetrics, UnifiedProducer

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.events.core.producer")


def test_producer_handle_stats_path() -> None:
    """Directly run stats parsing to cover branch logic; avoid relying on timing."""
    m = ProducerMetrics()
    p = object.__new__(UnifiedProducer)  # bypass __init__ safely for method call
    # Inject required attributes for _handle_stats (including logger for exception handler)
    p._metrics = m
    p._stats_callback = None
    p.logger = _test_logger
    payload = json.dumps({"msg_cnt": 1, "topics": {"t": {"partitions": {"0": {"msgq_cnt": 2, "rtt": {"avg": 5}}}}}})
    UnifiedProducer._handle_stats(p, payload)
    assert m.queue_size == 1 and m.avg_latency_ms > 0
