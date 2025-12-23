import os

from opentelemetry import trace
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
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from app.core.adaptive_sampling import create_adaptive_sampler
from app.core.logging import logger
from app.core.tracing.models import (
    InstrumentationReport,
    InstrumentationResult,
    InstrumentationStatus,
    LibraryInstrumentation,
)
from app.settings import get_settings


class TracingConfiguration:
    """Configuration for OpenTelemetry tracing."""

    def __init__(
        self,
        service_name: str,
        service_version: str = "1.0.0",
        otlp_endpoint: str | None = None,
        enable_console_exporter: bool = False,
        sampling_rate: float = 1.0,
        adaptive_sampling: bool = False,
    ) -> None:
        self.service_name = service_name
        self.service_version = service_version
        self.otlp_endpoint = otlp_endpoint
        self.enable_console_exporter = enable_console_exporter
        self.sampling_rate = sampling_rate
        self.adaptive_sampling = adaptive_sampling
        self._settings = get_settings()

    def create_resource(self) -> Resource:
        """Create OpenTelemetry resource with service metadata."""
        return Resource.create(
            {
                SERVICE_NAME: self.service_name,
                SERVICE_VERSION: self.service_version,
                "deployment.environment": self._get_environment(),
                "service.namespace": "integr8scode",
                "service.instance.id": os.environ.get("HOSTNAME", "unknown"),
            }
        )

    def create_sampler(self) -> Sampler:
        """Create appropriate sampler based on configuration."""
        if self.adaptive_sampling:
            return create_adaptive_sampler()

        if self.sampling_rate <= 0:
            return ALWAYS_OFF

        if self.sampling_rate >= 1.0:
            return ALWAYS_ON

        return TraceIdRatioBased(self.sampling_rate)

    def get_otlp_endpoint(self) -> str | None:
        """Get OTLP endpoint from config or environment."""
        if self.otlp_endpoint:
            return self.otlp_endpoint

        if self._settings.JAEGER_AGENT_HOST:
            return f"{self._settings.JAEGER_AGENT_HOST}:4317"

        return None

    def _get_environment(self) -> str:
        """Get deployment environment."""
        return "test" if self._settings.TESTING else "production"


class TracingInitializer:
    """Initializes OpenTelemetry tracing with instrumentation."""

    def __init__(self, config: TracingConfiguration) -> None:
        self.config = config
        self.instrumentation_report = InstrumentationReport()

    def initialize(self) -> InstrumentationReport:
        """Initialize tracing and instrument libraries."""
        provider = self._create_provider()
        self._configure_exporters(provider)
        trace.set_tracer_provider(provider)
        set_global_textmap(TraceContextTextMapPropagator())

        self._instrument_libraries()

        logger.info(
            f"OpenTelemetry tracing initialized for {self.config.service_name}",
            extra={"instrumentation_summary": self.instrumentation_report.get_summary()},
        )

        return self.instrumentation_report

    def _create_provider(self) -> TracerProvider:
        """Create tracer provider with resource and sampler."""
        return TracerProvider(resource=self.config.create_resource(), sampler=self.config.create_sampler())

    def _configure_exporters(self, provider: TracerProvider) -> None:
        """Configure span exporters."""
        otlp_endpoint = self.config.get_otlp_endpoint()
        if otlp_endpoint:
            otlp_exporter = OTLPSpanExporter(
                endpoint=otlp_endpoint,
                insecure=True,
            )
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

        if self.config.enable_console_exporter:
            console_exporter = ConsoleSpanExporter()
            provider.add_span_processor(BatchSpanProcessor(console_exporter))

    def _instrument_libraries(self) -> None:
        """Instrument all configured libraries."""
        libraries = self._get_libraries_to_instrument()

        for lib in libraries:
            result = self._instrument_library(lib)
            self.instrumentation_report.add_result(result)

    def _get_libraries_to_instrument(self) -> list[LibraryInstrumentation]:
        """Get list of libraries to instrument."""
        return [
            LibraryInstrumentation(
                name="fastapi",
                instrumentor=FastAPIInstrumentor(),
                config={
                    "tracer_provider": trace.get_tracer_provider(),
                    "excluded_urls": "health,metrics,docs,openapi.json",
                },
            ),
            LibraryInstrumentation(
                name="httpx",
                instrumentor=HTTPXClientInstrumentor(),
                config={"tracer_provider": trace.get_tracer_provider()},
            ),
            LibraryInstrumentation(
                name="pymongo",
                instrumentor=PymongoInstrumentor(),
                config={"tracer_provider": trace.get_tracer_provider()},
            ),
            LibraryInstrumentation(
                name="logging",
                instrumentor=LoggingInstrumentor(),
                config={"set_logging_format": True, "log_level": "INFO"},
            ),
        ]

    def _instrument_library(self, lib: LibraryInstrumentation) -> InstrumentationResult:
        """Instrument a single library and return result."""
        try:
            lib.instrumentor.instrument(**lib.config)
            return InstrumentationResult(library=lib.name, status=InstrumentationStatus.SUCCESS)
        except Exception as e:
            logger.warning(
                f"Failed to instrument {lib.name}", exc_info=True, extra={"library": lib.name, "error": str(e)}
            )
            return InstrumentationResult(library=lib.name, status=InstrumentationStatus.FAILED, error=e)


def init_tracing(
    service_name: str,
    service_version: str = "1.0.0",
    otlp_endpoint: str | None = None,
    enable_console_exporter: bool = False,
    sampling_rate: float = 1.0,
    adaptive_sampling: bool = False,
) -> InstrumentationReport:
    """Initialize OpenTelemetry tracing with the given configuration."""
    config = TracingConfiguration(
        service_name=service_name,
        service_version=service_version,
        otlp_endpoint=otlp_endpoint,
        enable_console_exporter=enable_console_exporter,
        sampling_rate=sampling_rate,
        adaptive_sampling=adaptive_sampling,
    )

    initializer = TracingInitializer(config)
    return initializer.initialize()
