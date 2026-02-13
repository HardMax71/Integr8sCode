import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.pymongo import PymongoInstrumentor
from opentelemetry.propagate import set_global_textmap
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON, ParentBased, Sampler, TraceIdRatioBased
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from app.settings import Settings


class Tracer:
    """DI-managed OpenTelemetry tracer. Initialization happens on construction."""

    def __init__(self, settings: Settings, logger: structlog.stdlib.BoundLogger) -> None:
        name = settings.TRACING_SERVICE_NAME
        rate = settings.TRACING_SAMPLING_RATE

        resource = Resource.create({
            SERVICE_NAME: name,
            SERVICE_VERSION: settings.TRACING_SERVICE_VERSION,
            "deployment.environment": "test" if settings.TESTING else "production",
            "service.namespace": "integr8scode",
            "service.instance.id": settings.HOSTNAME,
        })

        sampler: Sampler
        if rate <= 0:
            sampler = ALWAYS_OFF
        elif rate >= 1.0:
            sampler = ALWAYS_ON
        else:
            sampler = ParentBased(root=TraceIdRatioBased(rate))

        provider = TracerProvider(resource=resource, sampler=sampler)

        if settings.OTLP_TRACES_ENDPOINT:
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(
                    endpoint=settings.OTLP_TRACES_ENDPOINT,
                    insecure=settings.OTLP_TRACES_ENDPOINT.startswith("http://"),
                ))
            )

        trace.set_tracer_provider(provider)
        set_global_textmap(TraceContextTextMapPropagator())

        tp = trace.get_tracer_provider()
        HTTPXClientInstrumentor().instrument(tracer_provider=tp)
        PymongoInstrumentor().instrument(tracer_provider=tp)
        LoggingInstrumentor().instrument(set_logging_format=False, log_level="INFO")

        logger.info("Tracing initialized", service_name=name)
