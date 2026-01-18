import pytest
from app.core.metrics import HealthMetrics
from app.settings import Settings

pytestmark = pytest.mark.unit


def test_health_metrics_methods(test_settings: Settings) -> None:
    """Test with no-op metrics."""
    m = HealthMetrics(test_settings)
    m.record_health_check_duration(0.1, "liveness", "basic")
    m.record_health_check_failure("readiness", "db", "timeout")
    m.update_health_check_status(1, "liveness", "basic")
    m.record_health_status("svc", "healthy")
    m.record_service_health_score("svc", 95.0)
    m.update_liveness_status(True, "app")
    m.update_readiness_status(False, "app")
    m.record_dependency_health("mongo", True, 0.2)
    m.record_health_check_timeout("readiness", "db")
    m.update_component_health("kafka", True)


def test_rate_limit_metrics_methods() -> None:
    """Test with no-op metrics."""
