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
