import os
from dataclasses import dataclass, field

from app.domain.enums.kafka import KafkaTopic


@dataclass
class K8sWorkerConfig:

    # Kafka settings
    kafka_bootstrap_servers: str | None = None
    consumer_group: str = "kubernetes-worker"
    topics: list[KafkaTopic] = field(default_factory=lambda: [KafkaTopic.EXECUTION_TASKS])

    # Kubernetes settings
    namespace: str = os.environ.get("K8S_NAMESPACE", "integr8scode")
    kubeconfig_path: str | None = os.environ.get("KUBECONFIG", None)
    in_cluster: bool = False

    # Worker settings
    max_concurrent_pods: int = 10
    pod_creation_timeout: int = 60
    pod_watch_timeout: int = 300

    # Resource defaults
    default_cpu_request: str = "100m"
    default_cpu_limit: str = "1000m"
    default_memory_request: str = "128Mi"
    default_memory_limit: str = "1024Mi"

    # Retry settings
    max_retries: int = 3
    retry_delay_seconds: int = 5

    # Monitoring
    enable_pod_metrics: bool = True
    metrics_port: int = 9090
