import logging

import pytest

from app.core.metrics.context import (
    get_connection_metrics,
    get_coordinator_metrics,
)

_test_logger = logging.getLogger("test.core.metrics.context")

pytestmark = pytest.mark.unit


def test_metrics_context_returns_initialized_metrics() -> None:
    """Test metrics context returns initialized metrics from session fixture."""
    # Metrics are initialized by the session-scoped fixture in conftest.py
    c1 = get_connection_metrics()
    c2 = get_connection_metrics()
    assert c1 is c2  # same instance per context

    d1 = get_coordinator_metrics()
    d2 = get_coordinator_metrics()
    assert d1 is d2

