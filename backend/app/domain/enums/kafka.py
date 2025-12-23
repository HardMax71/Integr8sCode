from typing import Dict, Set

from app.core.utils import StringEnum
from app.domain.enums.events import EventType


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
    USER_SETTINGS_THEME_EVENTS = "user_settings_theme_events"
    USER_SETTINGS_NOTIFICATION_EVENTS = "user_settings_notification_events"
    USER_SETTINGS_EDITOR_EVENTS = "user_settings_editor_events"

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
    EVENT_BUS_STREAM = "event_bus_stream"
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


# Consumer group topic subscriptions
CONSUMER_GROUP_SUBSCRIPTIONS: Dict[GroupId, Set[KafkaTopic]] = {
    GroupId.EXECUTION_COORDINATOR: {
        KafkaTopic.EXECUTION_EVENTS,
        KafkaTopic.EXECUTION_RESULTS,
    },
    GroupId.K8S_WORKER: {
        KafkaTopic.EXECUTION_EVENTS,
    },
    GroupId.POD_MONITOR: {
        KafkaTopic.POD_EVENTS,
        KafkaTopic.POD_STATUS_UPDATES,
    },
    GroupId.RESULT_PROCESSOR: {
        KafkaTopic.EXECUTION_RESULTS,
    },
    GroupId.SAGA_ORCHESTRATOR: {
        # Orchestrator is triggered by domain events, specifically EXECUTION_REQUESTED,
        # and emits commands on SAGA_COMMANDS.
        KafkaTopic.EXECUTION_EVENTS,
        KafkaTopic.SAGA_COMMANDS,
    },
    GroupId.WEBSOCKET_GATEWAY: {
        KafkaTopic.EXECUTION_EVENTS,
        KafkaTopic.EXECUTION_RESULTS,
        KafkaTopic.POD_EVENTS,
        KafkaTopic.POD_STATUS_UPDATES,
        KafkaTopic.EXECUTION_RESULTS,
    },
    GroupId.NOTIFICATION_SERVICE: {
        KafkaTopic.NOTIFICATION_EVENTS,
        KafkaTopic.EXECUTION_RESULTS,
    },
    GroupId.DLQ_PROCESSOR: {
        KafkaTopic.DEAD_LETTER_QUEUE,
    },
}

# Consumer group event filters
CONSUMER_GROUP_EVENTS: Dict[GroupId, Set[EventType]] = {
    GroupId.EXECUTION_COORDINATOR: {
        EventType.EXECUTION_REQUESTED,
        EventType.EXECUTION_COMPLETED,
        EventType.EXECUTION_FAILED,
        EventType.EXECUTION_CANCELLED,
    },
    GroupId.K8S_WORKER: {
        EventType.EXECUTION_STARTED,
    },
    GroupId.POD_MONITOR: {
        EventType.POD_CREATED,
        EventType.POD_RUNNING,
        EventType.POD_SUCCEEDED,
        EventType.POD_FAILED,
    },
    GroupId.RESULT_PROCESSOR: {
        EventType.EXECUTION_COMPLETED,
        EventType.EXECUTION_FAILED,
        EventType.EXECUTION_TIMEOUT,
    },
    GroupId.SAGA_ORCHESTRATOR: set(),
    GroupId.WEBSOCKET_GATEWAY: {
        EventType.EXECUTION_REQUESTED,
        EventType.EXECUTION_STARTED,
        EventType.EXECUTION_COMPLETED,
        EventType.EXECUTION_FAILED,
        EventType.POD_CREATED,
        EventType.POD_RUNNING,
        EventType.RESULT_STORED,
    },
    GroupId.NOTIFICATION_SERVICE: {
        EventType.NOTIFICATION_CREATED,
        EventType.EXECUTION_COMPLETED,
        EventType.EXECUTION_FAILED,
        EventType.EXECUTION_TIMEOUT,
    },
    GroupId.DLQ_PROCESSOR: set(),
}
