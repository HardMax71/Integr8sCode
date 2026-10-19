import structlog
from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource

from app.settings import Settings

# The host's CPU and memory come from the collector's host_metrics receiver, so a process reports only its own
PROCESS_METRICS: dict[str, list[str] | None] = {
    "process.cpu.time": ["user", "system"],
    "process.cpu.utilization": ["user", "system"],
    "process.memory.usage": None,
    "process.memory.virtual": None,
    "process.thread.count": None,
    "process.open_file_descriptor.count": None,
}


def setup_metrics(settings: Settings, logger: structlog.stdlib.BoundLogger) -> None:
    """Install the global MeterProvider that exports through OTLP, and this process's CPU and memory metrics.

    The OpenTelemetry instrumentations take their meters from the global provider, so this runs before them.
    Without an OTLP endpoint (tests) the no-op provider stays.
    """
    if not settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        logger.info("Metrics OTLP export disabled", endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
        return

    resource = Resource.create(
        {
            SERVICE_NAME: settings.SERVICE_NAME,
            SERVICE_VERSION: settings.SERVICE_VERSION,
            "deployment.environment": settings.ENVIRONMENT,
        }
    )
    exporter = OTLPMetricExporter(
        endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
        insecure=settings.OTEL_EXPORTER_OTLP_ENDPOINT.startswith("http://"),
    )
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(exporter=exporter, export_interval_millis=60000)],
    )
    metrics.set_meter_provider(meter_provider)
    SystemMetricsInstrumentor(config=PROCESS_METRICS).instrument(meter_provider=meter_provider)

    logger.info("OpenTelemetry metrics configured with OTLP exporter")
