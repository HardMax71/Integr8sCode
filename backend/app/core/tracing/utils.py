from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry import context, propagate, trace
from opentelemetry.trace import SpanKind, Status, StatusCode


def get_tracer() -> trace.Tracer:
    """Get a tracer for the current module."""
    return trace.get_tracer(__name__)


@contextmanager
def trace_span(
    name: str,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: dict[str, Any] | None = None,
    set_status_on_exception: bool = True,
    tracer: trace.Tracer | None = None,
) -> Generator[trace.Span, None, None]:
    """
    Context manager for creating a traced span.

    Args:
        name: Name of the span
        kind: Kind of span (INTERNAL, CLIENT, SERVER, etc.)
        attributes: Additional attributes to set on the span
        set_status_on_exception: Whether to set error status on exception
        tracer: Optional tracer to use, defaults to module tracer

    Yields:
        The created span
    """
    if tracer is None:
        tracer = get_tracer()

    with tracer.start_as_current_span(name, kind=kind, attributes=attributes or {}) as span:
        try:
            yield span
        except Exception as e:
            if set_status_on_exception:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
            raise


def inject_trace_context(headers: dict[str, str]) -> dict[str, str]:
    """
    Inject current trace context into headers for propagation.

    Args:
        headers: Existing headers dictionary

    Returns:
        Headers with trace context injected
    """
    propagation_headers = headers.copy()
    propagate.inject(propagation_headers)
    return propagation_headers


def extract_trace_context(headers: dict[str, str]) -> context.Context:
    """
    Extract trace context from headers.

    Args:
        headers: Headers containing trace context

    Returns:
        Extracted OpenTelemetry context
    """
    return propagate.extract(headers)


def add_span_attributes(**attributes: Any) -> None:
    """
    Add attributes to the current span.

    Args:
        **attributes: Key-value pairs to add as span attributes
    """
    span = trace.get_current_span()
    if span and span.is_recording():
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)


