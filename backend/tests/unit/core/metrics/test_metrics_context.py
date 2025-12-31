import logging

from app.core.metrics.context import (
    MetricsContext,
    get_connection_metrics,
    get_coordinator_metrics,
)

_test_logger = logging.getLogger("test.core.metrics.context")


def test_metrics_context_lazy_and_reset() -> None:
    """Test metrics context lazy loading and reset with no-op metrics."""
    # Get metrics instances - will use NoOpMeterProvider automatically
    c1 = get_connection_metrics()
    c2 = get_connection_metrics()
    assert c1 is c2  # same instance per context

    d1 = get_coordinator_metrics()
    MetricsContext.reset_all(_test_logger)
    # after reset, new instances are created lazily
    c3 = get_connection_metrics()
    assert c3 is not c1
    d2 = get_coordinator_metrics()
    assert d2 is not d1

