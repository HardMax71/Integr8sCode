import asyncio
import functools
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any, ParamSpec, TypeVar

from opentelemetry import context, propagate, trace
from opentelemetry.trace import SpanKind, Status, StatusCode

P = ParamSpec("P")
R = TypeVar("R")


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


def trace_method(
    name: str | None = None, kind: SpanKind = SpanKind.INTERNAL, attributes: dict[str, Any] | None = None
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Decorator for tracing method calls.

    Args:
        name: Custom span name, defaults to module.method_name
        kind: Kind of span (INTERNAL, CLIENT, SERVER, etc.)
        attributes: Additional attributes to set on the span

    Returns:
        Decorated function with tracing
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        span_name = name or f"{func.__module__}.{func.__name__}"

        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with trace_span(span_name, kind=kind, attributes=attributes):
                return await func(*args, **kwargs)  # type: ignore[misc, no-any-return]

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with trace_span(span_name, kind=kind, attributes=attributes):
                return func(*args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper

    return decorator


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


def add_span_event(name: str, attributes: dict[str, Any] | None = None) -> None:
    """
    Add an event to the current span.

    Args:
        name: Name of the event
        attributes: Optional attributes for the event
    """
    span = trace.get_current_span()
    if span and span.is_recording():
        span.add_event(name, attributes=attributes or {})


def set_span_status(code: StatusCode, description: str | None = None) -> None:
    """
    Set the status of the current span.

    Args:
        code: Status code (OK, ERROR, UNSET)
        description: Optional description
    """
    span = trace.get_current_span()
    if span and span.is_recording():
        span.set_status(Status(code, description))


def get_current_trace_id() -> str | None:
    """
    Get the current trace ID as a hex string.

    Returns:
        Trace ID as 32-character hex string, or None if no active trace
    """
    span = trace.get_current_span()
    if span and span.is_recording():
        span_context = span.get_span_context()
        if span_context.is_valid:
            return format(span_context.trace_id, "032x")
    return None


def get_current_span_id() -> str | None:
    """
    Get the current span ID as a hex string.

    Returns:
        Span ID as 16-character hex string, or None if no active span
    """
    span = trace.get_current_span()
    if span and span.is_recording():
        span_context = span.get_span_context()
        if span_context.is_valid:
            return format(span_context.span_id, "016x")
    return None
