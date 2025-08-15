"""Configuration for KubernetesWorker service"""

import os
from dataclasses import dataclass, field
from typing import Optional

from app.schemas_avro.event_schemas import KafkaTopic


@dataclass
class K8sWorkerConfig:
    """Configuration for KubernetesWorker"""

    # Kafka settings
    kafka_bootstrap_servers: Optional[str] = None
    consumer_group: str = "kubernetes-worker"
    topics: list[str] = field(default_factory=lambda: [KafkaTopic.EXECUTION_TASKS])

    # Kubernetes settings
    namespace: str = os.environ.get("K8S_NAMESPACE", "integr8scode")
    kubeconfig_path: Optional[str] = os.environ.get("KUBECONFIG", None)
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

    # Security settings
    enable_network_policies: bool = True
    enable_security_context: bool = True
    run_as_non_root: bool = True
    read_only_root_filesystem: bool = True

    # Monitoring
    enable_pod_metrics: bool = True
    metrics_port: int = 9090

    def __post_init__(self) -> None:
        # Additional post-initialization logic can go here if needed
        pass
