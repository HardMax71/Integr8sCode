import pytest
from app.core.metrics.base import BaseMetrics

pytestmark = pytest.mark.unit


class DummyMetrics(BaseMetrics):
    def __init__(self) -> None:
        self.created = False
        super().__init__(meter_name="dummy")
        
    def _create_instruments(self) -> None:  # noqa: D401
        self.created = True


def test_base_metrics_initializes_meter_and_instruments() -> None:
    """Test that BaseMetrics initializes properly with no-op metrics."""
    # Create DummyMetrics instance - will use NoOpMeterProvider automatically
    m = DummyMetrics()
    
    # Verify that the BaseMetrics init was called and instruments were created
    assert m.created is True
    assert m._meter is not None  # Meter exists (will be NoOpMeter)
    
    # close is no-op
    m.close()

