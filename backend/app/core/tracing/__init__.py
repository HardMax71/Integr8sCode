# Re-export commonly used OpenTelemetry types for convenience
from opentelemetry import context
from opentelemetry.trace import SpanKind, Status, StatusCode

# Import configuration and initialization
from app.core.tracing.config import (
    TracingConfiguration,
    TracingInitializer,
    init_tracing,
)
from app.core.tracing.models import (
    EventAttributes,
    InstrumentationReport,
    InstrumentationResult,
    InstrumentationStatus,
    TracerManager,
)

# Import utilities and decorators
from app.core.tracing.utils import (
    add_span_attributes,
    extract_trace_context,
    get_tracer,
    inject_trace_context,
    trace_span,
)

__all__ = [
    # Models and enums
    "EventAttributes",
    "InstrumentationReport",
    "InstrumentationResult",
    "InstrumentationStatus",
    "TracerManager",
    # Configuration and initialization
    "TracingConfiguration",
    "TracingInitializer",
    "init_tracing",
    # Utilities and decorators
    "add_span_attributes",
    "extract_trace_context",
    "get_tracer",
    "inject_trace_context",
    "trace_span",
    # OpenTelemetry types
    "context",
    "SpanKind",
    "Status",
    "StatusCode",
]
