import importlib

import pytest
from app.domain.enums import KafkaTopic
from app.services.pod_monitor import PodMonitorConfig

pytestmark = pytest.mark.unit


def test_pod_monitor_config_defaults() -> None:
    cfg = PodMonitorConfig()
    assert cfg.namespace == "integr8scode"
    assert isinstance(cfg.pod_events_topic, KafkaTopic) and cfg.pod_events_topic
    assert isinstance(cfg.execution_completed_topic, KafkaTopic)
    assert cfg.ignored_pod_phases == []


def test_package_exports() -> None:
    mod = importlib.import_module("app.services.pod_monitor")
    assert set(mod.__all__) == {
        "ErrorType",
        "PodContext",
        "PodEventMapper",
        "PodMonitor",
        "PodMonitorConfig",
        "WatchEventType",
    }
