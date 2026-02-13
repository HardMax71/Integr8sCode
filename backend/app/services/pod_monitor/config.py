from dataclasses import dataclass, field

from app.domain.enums import EventType, KafkaTopic
from app.infrastructure.kafka import get_topic_for_event
from app.services.pod_monitor.event_mapper import PodPhase


@dataclass
class PodMonitorConfig:
    """Configuration for PodMonitor service"""

    # Kafka settings
    pod_events_topic: KafkaTopic = get_topic_for_event(EventType.POD_CREATED)
    execution_events_topic: KafkaTopic = get_topic_for_event(EventType.EXECUTION_REQUESTED)
    execution_completed_topic: KafkaTopic = get_topic_for_event(EventType.EXECUTION_COMPLETED)
    execution_failed_topic: KafkaTopic = get_topic_for_event(EventType.EXECUTION_FAILED)

    # Kubernetes settings
    namespace: str = "integr8scode"
    kubeconfig_path: str | None = None
    in_cluster: bool = False

    # Watch settings
    label_selector: str = "app=integr8s,component=executor"
    field_selector: str | None = None
    watch_timeout_seconds: int = 300  # 5 minutes

    # Monitoring settings
    enable_metrics: bool = True
    metrics_port: int = 9091

    # Event filtering
    ignored_pod_phases: list[PodPhase] = field(default_factory=list)
