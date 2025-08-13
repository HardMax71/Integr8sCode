import asyncio
import functools
import os
from contextlib import contextmanager
from typing import Any, Callable, Dict, Generator, Optional

from opentelemetry import context, trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.pymongo import PymongoInstrumentor
from opentelemetry.propagate import set_global_textmap
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON, Sampler, TraceIdRatioBased
from opentelemetry.trace import SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from app.config import get_settings
from app.core.logging import logger


# Span attribute constants for consistency
class EventAttributes:
    """Common attributes for event-driven architecture"""
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


class TracerManager:
    """Singleton manager for OpenTelemetry tracer"""
    _instance: Optional['TracerManager'] = None
    _initialized: bool

    def __new__(cls) -> 'TracerManager':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # Initialize the instance attribute
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if not hasattr(self, '_initialized') or not self._initialized:
            self._tracer: Optional[trace.Tracer] = None
            self._initialized = True

    def get_tracer(self) -> trace.Tracer:
        """Get or create tracer instance"""
        if self._tracer is None:
            self._tracer = trace.get_tracer(__name__)
        return self._tracer


def get_tracer_manager() -> TracerManager:
    """Get the singleton TracerManager instance"""
    return TracerManager()


def get_tracer() -> trace.Tracer:
    """Get or create tracer instance"""
    return get_tracer_manager().get_tracer()


def init_tracing(
        service_name: str,
        service_version: str = "1.0.0",
        otlp_endpoint: Optional[str] = None,
        enable_console_exporter: bool = False,
        sampling_rate: float = 1.0,
        adaptive_sampling: bool = False
) -> None:
    """Initialize OpenTelemetry tracing"""
    settings = get_settings()

    # Create resource
    resource = Resource.create({
        SERVICE_NAME: service_name,
        SERVICE_VERSION: service_version,
        "deployment.environment": "production" if not settings.TESTING else "test",
        "service.namespace": "integr8scode",
        "service.instance.id": os.environ.get("HOSTNAME", "unknown"),
    })

    # Configure sampler based on sampling rate
    sampler: Sampler
    if adaptive_sampling:
        # Use adaptive sampling for production environments
        from app.core.adaptive_sampling import create_adaptive_sampler
        sampler = create_adaptive_sampler()
        logger.info(f"Using adaptive sampling with base rate: {sampling_rate}")
    elif sampling_rate <= 0:
        sampler = ALWAYS_OFF
        logger.info(f"Tracing disabled (sampling rate: {sampling_rate})")
    elif sampling_rate >= 1.0:
        sampler = ALWAYS_ON
        logger.info(f"Tracing all requests (sampling rate: {sampling_rate})")
    else:
        sampler = TraceIdRatioBased(sampling_rate)
        logger.info(f"Tracing {sampling_rate * 100:.1f}% of requests")

    # Create tracer provider with sampler
    provider = TracerProvider(
        resource=resource,
        sampler=sampler
    )

    # Add OTLP exporter
    if otlp_endpoint or settings.JAEGER_AGENT_HOST:
        # OTLP endpoint - can be Jaeger with OTLP support or any OTLP collector
        endpoint = otlp_endpoint or f"{settings.JAEGER_AGENT_HOST or 'jaeger'}:4317"
        otlp_exporter = OTLPSpanExporter(
            endpoint=endpoint,
            insecure=True,  # Use insecure connection for local development
        )
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        logger.info(f"OTLP tracing enabled for service: {service_name} (endpoint: {endpoint})")

    # Add console exporter for debugging
    if enable_console_exporter:
        console_exporter = ConsoleSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(console_exporter))

    # Set global tracer provider
    trace.set_tracer_provider(provider)

    # Set global propagator
    set_global_textmap(TraceContextTextMapPropagator())

    # Auto-instrument libraries
    instrument_libraries()

    logger.info(f"OpenTelemetry tracing initialized for {service_name}")


def instrument_libraries() -> None:
    """Auto-instrument common libraries"""
    try:
        # FastAPI
        FastAPIInstrumentor().instrument(
            tracer_provider=trace.get_tracer_provider(),
            excluded_urls="health,metrics,docs,openapi.json"
        )
    except Exception as e:
        logger.warning(f"Failed to instrument FastAPI: {e}")

    try:
        # HTTP client
        HTTPXClientInstrumentor().instrument(
            tracer_provider=trace.get_tracer_provider()
        )
    except Exception as e:
        logger.warning(f"Failed to instrument HTTPX: {e}")

    try:
        # MongoDB
        PymongoInstrumentor().instrument(
            tracer_provider=trace.get_tracer_provider()
        )
    except Exception as e:
        logger.warning(f"Failed to instrument PyMongo: {e}")

    try:
        # Logging correlation
        LoggingInstrumentor().instrument(
            set_logging_format=True,
            log_level="INFO"
        )
    except Exception as e:
        logger.warning(f"Failed to instrument logging: {e}")


@contextmanager
def trace_span(
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Optional[Dict[str, Any]] = None,
        set_status_on_exception: bool = True
) -> Generator[trace.Span, None, None]:
    """Context manager for creating a traced span"""
    tracer = get_tracer()

    with tracer.start_as_current_span(
            name,
            kind=kind,
            attributes=attributes or {}
    ) as span:
        try:
            yield span
        except Exception as e:
            if set_status_on_exception:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
            raise


def trace_method(
        name: Optional[str] = None,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Optional[Dict[str, Any]] = None
) -> Callable:
    """Decorator for tracing methods"""

    def decorator(func: Callable) -> Callable:
        span_name = name or f"{func.__module__}.{func.__name__}"

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            with trace_span(span_name, kind=kind, attributes=attributes):
                return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with trace_span(span_name, kind=kind, attributes=attributes):
                return func(*args, **kwargs)

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator


def inject_trace_context(headers: Dict[str, str]) -> Dict[str, str]:
    """Inject trace context into headers for propagation"""
    from opentelemetry import propagate

    # Create a copy to avoid modifying original
    propagation_headers = headers.copy()

    # Inject trace context
    propagate.inject(propagation_headers)

    return propagation_headers


def extract_trace_context(headers: Dict[str, str]) -> context.Context:
    """Extract trace context from headers"""
    from opentelemetry import propagate

    # Extract context from headers
    return propagate.extract(headers)


def add_span_attributes(**attributes: Any) -> None:
    """Add attributes to current span"""
    span = trace.get_current_span()
    if span and span.is_recording():
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)


def add_span_event(name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
    """Add event to current span"""
    span = trace.get_current_span()
    if span and span.is_recording():
        span.add_event(name, attributes=attributes or {})


def set_span_status(code: StatusCode, description: Optional[str] = None) -> None:
    """Set status on current span"""
    span = trace.get_current_span()
    if span and span.is_recording():
        span.set_status(Status(code, description))


def get_current_trace_id() -> Optional[str]:
    """Get current trace ID"""
    span = trace.get_current_span()
    if span and span.is_recording():
        span_context = span.get_span_context()
        if span_context.is_valid:
            return format(span_context.trace_id, '032x')
    return None


def get_current_span_id() -> Optional[str]:
    """Get current span ID"""
    span = trace.get_current_span()
    if span and span.is_recording():
        span_context = span.get_span_context()
        if span_context.is_valid:
            return format(span_context.span_id, '016x')
    return None
