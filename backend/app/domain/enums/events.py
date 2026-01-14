from app.core.utils import StringEnum


class EventType(StringEnum):
    """Event types used throughout the system."""

    # Execution lifecycle events
    EXECUTION_REQUESTED = "execution_requested"
    EXECUTION_ACCEPTED = "execution_accepted"
    EXECUTION_QUEUED = "execution_queued"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_RUNNING = "execution_running"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    EXECUTION_TIMEOUT = "execution_timeout"
    EXECUTION_CANCELLED = "execution_cancelled"

    # Pod lifecycle events
    POD_CREATED = "pod_created"
    POD_SCHEDULED = "pod_scheduled"
    POD_RUNNING = "pod_running"
    POD_SUCCEEDED = "pod_succeeded"
    POD_FAILED = "pod_failed"
    POD_TERMINATED = "pod_terminated"
    POD_DELETED = "pod_deleted"

    # User events
    USER_REGISTERED = "user_registered"
    USER_LOGIN = "user_login"
    USER_LOGGED_IN = "user_logged_in"
    USER_LOGGED_OUT = "user_logged_out"
    USER_UPDATED = "user_updated"
    USER_DELETED = "user_deleted"

    # User settings events
    USER_SETTINGS_UPDATED = "user_settings_updated"

    # Notification events
    NOTIFICATION_CREATED = "notification_created"
    NOTIFICATION_SENT = "notification_sent"
    NOTIFICATION_DELIVERED = "notification_delivered"
    NOTIFICATION_FAILED = "notification_failed"
    NOTIFICATION_READ = "notification_read"
    NOTIFICATION_CLICKED = "notification_clicked"
    NOTIFICATION_PREFERENCES_UPDATED = "notification_preferences_updated"

    # Script events
    SCRIPT_SAVED = "script_saved"
    SCRIPT_DELETED = "script_deleted"
    SCRIPT_SHARED = "script_shared"

    # Security events
    SECURITY_VIOLATION = "security_violation"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    AUTH_FAILED = "auth_failed"

    # Resource events
    RESOURCE_LIMIT_EXCEEDED = "resource_limit_exceeded"
    QUOTA_EXCEEDED = "quota_exceeded"

    # System events
    SYSTEM_ERROR = "system_error"
    SERVICE_UNHEALTHY = "service_unhealthy"
    SERVICE_RECOVERED = "service_recovered"

    # Result events
    RESULT_STORED = "result_stored"
    RESULT_FAILED = "result_failed"

    # Saga events
    SAGA_STARTED = "saga_started"
    SAGA_COMPLETED = "saga_completed"
    SAGA_FAILED = "saga_failed"
    SAGA_CANCELLED = "saga_cancelled"
    SAGA_COMPENSATING = "saga_compensating"
    SAGA_COMPENSATED = "saga_compensated"

    # Saga command events (orchestration)
    CREATE_POD_COMMAND = "create_pod_command"
    DELETE_POD_COMMAND = "delete_pod_command"
    ALLOCATE_RESOURCES_COMMAND = "allocate_resources_command"
    RELEASE_RESOURCES_COMMAND = "release_resources_command"

    # DLQ events
    DLQ_MESSAGE_RECEIVED = "dlq_message_received"
    DLQ_MESSAGE_RETRIED = "dlq_message_retried"
    DLQ_MESSAGE_DISCARDED = "dlq_message_discarded"
