"""Configuration for PodMonitor service"""

import os
from dataclasses import dataclass, field
from typing import Optional

from app.events.core.mapping import get_topic_name
from app.schemas_avro.event_schemas import EventType
from app.services.pod_monitor.event_mapper import PodPhase


@dataclass
class PodMonitorConfig:
    """Configuration for PodMonitor service"""

    # Kafka settings
    kafka_bootstrap_servers: Optional[str] = None
    pod_events_topic: str = get_topic_name(EventType.POD_CREATED)
    execution_events_topic: str = get_topic_name(EventType.EXECUTION_REQUESTED)
    execution_completed_topic: str = get_topic_name(EventType.EXECUTION_COMPLETED)
    execution_failed_topic: str = get_topic_name(EventType.EXECUTION_FAILED)

    # Kubernetes settings
    namespace: str = os.environ.get("K8S_NAMESPACE", "integr8scode")
    kubeconfig_path: Optional[str] = os.environ.get("KUBECONFIG", None)
    in_cluster: bool = False

    # Watch settings
    label_selector: str = "app=integr8s,component=executor"
    field_selector: Optional[str] = None
    watch_timeout_seconds: int = 300  # 5 minutes
    watch_reconnect_delay: int = 5
    max_reconnect_attempts: int = 10

    # Monitoring settings
    enable_metrics: bool = True
    metrics_port: int = 9091

    # State reconciliation
    reconcile_interval_seconds: int = 300  # 5 minutes
    enable_state_reconciliation: bool = True

    # Event filtering
    ignored_pod_phases: list[PodPhase] = field(default_factory=list)
