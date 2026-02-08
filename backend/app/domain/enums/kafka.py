from app.core.utils import StringEnum


class KafkaTopic(StringEnum):
    """Kafka topic names used throughout the system."""

    EXECUTION_EVENTS = "execution_events"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    EXECUTION_TIMEOUT = "execution_timeout"
    EXECUTION_REQUESTS = "execution_requests"
    EXECUTION_COMMANDS = "execution_commands"
    EXECUTION_TASKS = "execution_tasks"

    # Pod topics
    POD_EVENTS = "pod_events"
    POD_STATUS_UPDATES = "pod_status_updates"
    POD_RESULTS = "pod_results"

    # Result topics
    EXECUTION_RESULTS = "execution_results"

    # User topics
    USER_EVENTS = "user_events"
    USER_NOTIFICATIONS = "user_notifications"
    USER_SETTINGS_EVENTS = "user_settings_events"

    # Script topics
    SCRIPT_EVENTS = "script_events"

    # Security topics
    SECURITY_EVENTS = "security_events"

    # Resource topics
    RESOURCE_EVENTS = "resource_events"

    # Notification topics
    NOTIFICATION_EVENTS = "notification_events"

    # System topics
    SYSTEM_EVENTS = "system_events"

    # Saga topics
    SAGA_EVENTS = "saga_events"
    SAGA_COMMANDS = "saga_commands"

    # Infrastructure topics
    DEAD_LETTER_QUEUE = "dead_letter_queue"
    DLQ_EVENTS = "dlq_events"
    WEBSOCKET_EVENTS = "websocket_events"


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
    DLQ_PROCESSOR = "dlq-processor"
    DLQ_MANAGER = "dlq-manager"
