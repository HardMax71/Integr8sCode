from dataclasses import dataclass, field

from app.services.pod_monitor.event_mapper import PodPhase


@dataclass
class PodMonitorConfig:
    """Configuration for PodMonitor service"""

    # Kubernetes settings
    namespace: str = "integr8scode"
    kubeconfig_path: str | None = None
    in_cluster: bool = False

    # Watch settings
    label_selector: str = "app=integr8s,component=executor"
    field_selector: str | None = None
    watch_timeout_seconds: int = 30
    # A watch that failed waits this long before the next, so an unreachable API isn't asked in a tight loop
    watch_retry_seconds: int = 5

    # Monitoring settings
    enable_metrics: bool = True
    metrics_port: int = 9091

    # Event filtering
    ignored_pod_phases: list[PodPhase] = field(default_factory=list)
