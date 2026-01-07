import importlib

import pytest
from app.services.pod_monitor.config import PodMonitorConfig

pytestmark = pytest.mark.unit


def test_pod_monitor_config_defaults() -> None:
    cfg = PodMonitorConfig()
    assert cfg.namespace in {"integr8scode", "default"}
    assert isinstance(cfg.pod_events_topic, str) and cfg.pod_events_topic
    assert isinstance(cfg.execution_completed_topic, str)
    assert cfg.ignored_pod_phases == []


def test_package_exports() -> None:
    mod = importlib.import_module("app.services.pod_monitor")
    assert set(mod.__all__) == {"PodMonitor", "PodMonitorConfig", "PodEventMapper"}
