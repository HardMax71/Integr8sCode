from app.domain.enums import EventType, ExecutionStatus

EXECUTION_TYPES: set[EventType] = {
    EventType.EXECUTION_REQUESTED,
    EventType.EXECUTION_ACCEPTED,
    EventType.EXECUTION_QUEUED,
    EventType.EXECUTION_STARTED,
    EventType.EXECUTION_RUNNING,
    EventType.EXECUTION_COMPLETED,
    EventType.EXECUTION_FAILED,
    EventType.EXECUTION_TIMEOUT,
    EventType.EXECUTION_CANCELLED,
}

POD_TYPES: set[EventType] = {
    EventType.POD_CREATED,
    EventType.POD_SCHEDULED,
    EventType.POD_RUNNING,
    EventType.POD_SUCCEEDED,
    EventType.POD_FAILED,
    EventType.POD_TERMINATED,
    EventType.POD_DELETED,
}

RESULT_TYPES: set[EventType] = {
    EventType.RESULT_STORED,
    EventType.RESULT_FAILED,
}

SECURITY_TYPES: set[EventType] = {
    EventType.SECURITY_VIOLATION,
    EventType.RATE_LIMIT_EXCEEDED,
    EventType.AUTH_FAILED,
}

USER_TYPES: set[EventType] = {
    EventType.USER_REGISTERED,
    EventType.USER_LOGIN,
    EventType.USER_LOGGED_IN,
    EventType.USER_LOGGED_OUT,
    EventType.USER_UPDATED,
    EventType.USER_DELETED,
    EventType.USER_SETTINGS_UPDATED,
}

# Events that signal the executor pod has reached a terminal state, so the pod monitor deletes the pod.
# A cancel deletes its pod in the execution scheduler instead.
EXECUTION_TERMINAL_EVENT_TYPES: frozenset[EventType] = frozenset(
    {
        EventType.EXECUTION_COMPLETED,
        EventType.EXECUTION_FAILED,
        EventType.EXECUTION_TIMEOUT,
    }
)

# Events that signal the full execution pipeline has concluded
# (result stored or execution failed before result could be stored).
# The SSE service uses this to close the execution stream.
EXECUTION_PIPELINE_TERMINAL_EVENT_TYPES: frozenset[EventType] = frozenset(
    {
        EventType.RESULT_STORED,
        EventType.RESULT_FAILED,
        EventType.EXECUTION_FAILED,
        EventType.EXECUTION_TIMEOUT,
    }
)

# The status a pod event moves its execution to; the result processor stores it and the SSE bridge sends it
POD_EVENT_STATUS: dict[EventType, ExecutionStatus] = {
    EventType.POD_SCHEDULED: ExecutionStatus.SCHEDULED,
    EventType.POD_RUNNING: ExecutionStatus.RUNNING,
}
