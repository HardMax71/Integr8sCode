from app.domain.enums import EventType

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

COMMAND_TYPES: set[EventType] = {
    EventType.CREATE_POD_COMMAND,
    EventType.DELETE_POD_COMMAND,
    EventType.ALLOCATE_RESOURCES_COMMAND,
    EventType.RELEASE_RESOURCES_COMMAND,
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

# Events that signal the executor pod has reached a terminal state.
# The pod monitor uses this to decide when to delete the pod.
# Note: EXECUTION_CANCELLED is excluded — cancellation triggers pod deletion
# via the saga's DeletePodCommandEvent compensation, not the monitor.
EXECUTION_TERMINAL_EVENT_TYPES: frozenset[EventType] = frozenset({
    EventType.EXECUTION_COMPLETED,
    EventType.EXECUTION_FAILED,
    EventType.EXECUTION_TIMEOUT,
})

# Events that signal the full execution pipeline has concluded
# (result stored or execution failed before result could be stored).
# The SSE service uses this to close the execution stream.
EXECUTION_PIPELINE_TERMINAL_EVENT_TYPES: frozenset[EventType] = frozenset({
    EventType.RESULT_STORED,
    EventType.RESULT_FAILED,
    EventType.EXECUTION_FAILED,
    EventType.EXECUTION_TIMEOUT,
})
