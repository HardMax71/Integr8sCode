import pytest

pytestmark = pytest.mark.unit


def test_rate_limit_metrics_methods() -> None:
    """Test with no-op metrics."""
