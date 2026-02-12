from app.core.utils import StringEnum


class GroupId(StringEnum):
    """Kafka consumer group IDs."""

    EXECUTION_COORDINATOR = "execution-coordinator"
    K8S_WORKER = "k8s-worker"
    POD_MONITOR = "pod-monitor"
    RESULT_PROCESSOR = "result-processor"
    SAGA_ORCHESTRATOR = "saga-orchestrator"
    EVENT_STORE_CONSUMER = "event-store-consumer"
    WEBSOCKET_GATEWAY = "websocket-gateway"
    NOTIFICATION_SERVICE = "notification-service"
