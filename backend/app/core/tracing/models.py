from dataclasses import dataclass, field
from typing import Any, Protocol

from opentelemetry import trace

from app.core.utils import StringEnum


class EventAttributes(StringEnum):
    """Standard attribute names for tracing events."""

    EVENT_TYPE = "event.type"
    EVENT_ID = "event.id"
    EXECUTION_ID = "execution.id"
    USER_ID = "user.id"
    POD_NAME = "k8s.pod.name"
    POD_NAMESPACE = "k8s.pod.namespace"
    KAFKA_TOPIC = "messaging.kafka.topic"
    KAFKA_PARTITION = "messaging.kafka.partition"
    KAFKA_OFFSET = "messaging.kafka.offset"
    KAFKA_KEY = "messaging.kafka.message_key"
    CONSUMER_GROUP = "messaging.kafka.consumer_group"
    SAGA_NAME = "saga.name"
    SAGA_ID = "saga.id"
    SAGA_STEP = "saga.step"
    QUEUE_NAME = "queue.name"
    QUEUE_POSITION = "queue.position"


class InstrumentationStatus(StringEnum):
    """Status of library instrumentation."""

    SUCCESS = "success"
    FAILED = "failed"
    NOT_ATTEMPTED = "not_attempted"


@dataclass
class InstrumentationResult:
    """Result of instrumenting a single library."""

    library: str
    status: InstrumentationStatus
    error: Exception | None = None


@dataclass
class InstrumentationReport:
    """Report of all instrumentation results."""

    results: dict[str, InstrumentationResult] = field(default_factory=dict)

    def add_result(self, result: InstrumentationResult) -> None:
        """Add an instrumentation result to the report."""
        self.results[result.library] = result

    def get_summary(self) -> dict[str, str]:
        """Get a summary of instrumentation statuses."""
        return {library: result.status for library, result in self.results.items()}

    def has_failures(self) -> bool:
        """Check if any instrumentation failed."""
        return any(result.status == InstrumentationStatus.FAILED for result in self.results.values())


class Instrumentor(Protocol):
    """Protocol for OpenTelemetry instrumentors."""

    def instrument(self, **kwargs: Any) -> None: ...


@dataclass
class LibraryInstrumentation:
    """Configuration for instrumenting a library."""

    name: str
    instrumentor: Instrumentor
    config: dict[str, Any] = field(default_factory=dict)


class TracerManager:
    """Manager for OpenTelemetry tracers."""

    def __init__(self, tracer_name: str = __name__) -> None:
        self._tracer_name = tracer_name
        self._tracer: trace.Tracer | None = None

    def get_tracer(self) -> trace.Tracer:
        """Get or create a tracer instance."""
        if self._tracer is None:
            self._tracer = trace.get_tracer(self._tracer_name)
        return self._tracer
