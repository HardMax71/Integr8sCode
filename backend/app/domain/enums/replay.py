from app.core.utils import StringEnum


class ReplayType(StringEnum):
    EXECUTION = "execution"
    TIME_RANGE = "time_range"
    EVENT_TYPE = "event_type"
    QUERY = "query"
    RECOVERY = "recovery"


class ReplayStatus(StringEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReplayTarget(StringEnum):
    KAFKA = "kafka"
    CALLBACK = "callback"
    FILE = "file"
    TEST = "test"
