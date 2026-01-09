import pytest

from app.core.metrics.base import BaseMetrics
from app.settings import Settings


pytestmark = pytest.mark.unit


class DummyMetrics(BaseMetrics):
    def __init__(self, settings: Settings) -> None:
        self.created = False
        super().__init__(settings, meter_name="dummy")

    def _create_instruments(self) -> None:  # noqa: D401
        self.created = True


def test_base_metrics_initializes_meter_and_instruments(test_settings: Settings) -> None:
    """Test that BaseMetrics initializes properly with no-op metrics."""
    # Create DummyMetrics instance - will use NoOpMeterProvider automatically
    m = DummyMetrics(test_settings)

    # Verify that the BaseMetrics init was called and instruments were created
    assert m.created is True
    assert m._meter is not None  # Meter exists (will be NoOpMeter)

    # close is no-op
    m.close()

