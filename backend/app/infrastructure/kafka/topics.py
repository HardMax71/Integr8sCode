from app.domain.enums import EventType, ExecutionStatus

RESULT_TYPES: set[EventType] = {
    EventType.RESULT_STORED,
    EventType.RESULT_FAILED,
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
