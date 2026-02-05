from app.core.utils import StringEnum


class KafkaTopic(StringEnum):
    """Kafka topic names for infrastructure topics only.

    Note: Domain event topics are derived from event class names via BaseEvent.topic().
    This enum is only for infrastructure topics (DLQ) that don't follow the event-class pattern.
    """

    DEAD_LETTER_QUEUE = "dead_letter_queue"
    DLQ_EVENTS = "dlq_events"


class GroupId(StringEnum):
    """Kafka consumer group IDs."""

    EXECUTION_COORDINATOR = "execution-coordinator"
    K8S_WORKER = "k8s-worker"
    POD_MONITOR = "pod-monitor"
    RESULT_PROCESSOR = "result-processor"
    SAGA_ORCHESTRATOR = "saga-orchestrator"
    NOTIFICATION_SERVICE = "notification-service"
    DLQ_MANAGER = "dlq-manager"
