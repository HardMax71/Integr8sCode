import os
import re
import time

import psutil
import structlog
from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.metrics import CallbackOptions, Observation
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.settings import Settings


class MetricsMiddleware:
    """Middleware to collect HTTP metrics using OpenTelemetry."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.meter = metrics.get_meter(__name__)

        # Create metrics instruments
        # --8<-- [start:instruments]
        self.request_counter = self.meter.create_counter(
            name="http_requests_total", description="Total number of HTTP requests", unit="requests"
        )

        self.request_duration = self.meter.create_histogram(
            name="http_request_duration_seconds", description="HTTP request duration in seconds", unit="seconds"
        )

        self.request_size = self.meter.create_histogram(
            name="http_request_size_bytes", description="HTTP request size in bytes", unit="bytes"
        )

        self.response_size = self.meter.create_histogram(
            name="http_response_size_bytes", description="HTTP response size in bytes", unit="bytes"
        )

        self.active_requests = self.meter.create_up_down_counter(
            name="http_requests_active", description="Number of active HTTP requests", unit="requests"
        )
        # --8<-- [end:instruments]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]

        # Skip metrics endpoint to avoid recursion
        if path == "/metrics":
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        path_template = self._get_path_template(path)

        # Increment active requests
        self.active_requests.add(1, {"method": method, "path": path_template})

        # Record request size
        headers = dict(scope["headers"])
        content_length = headers.get(b"content-length")
        if content_length:
            self.request_size.record(int(content_length), {"method": method, "path": path_template})

        start_time = time.time()
        response = _ResponseRecorder(send)
        raised = True
        try:
            await self.app(scope, receive, response)
            raised = False
        finally:
            duration = time.time() - start_time
            labels = {"method": method, "path": path_template, "status": "500" if raised else str(response.status)}

            self.request_counter.add(1, labels)
            self.request_duration.record(duration, labels)

            response_content_length = response.headers.get(b"content-length")
            if response_content_length:
                self.response_size.record(int(response_content_length), labels)

            self.active_requests.add(-1, {"method": method, "path": path_template})

    # --8<-- [start:path_template]
    @staticmethod
    def _get_path_template(path: str) -> str:
        """Convert path to template for lower cardinality."""
        # Common patterns to replace

        # UUID pattern
        path = re.sub(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "/{id}", path)

        # Numeric IDs
        path = re.sub(r"/\d+", "/{id}", path)

        # MongoDB ObjectIds
        path = re.sub(r"/[0-9a-f]{24}", "/{id}", path)

        return path

    # --8<-- [end:path_template]


class _ResponseRecorder:
    """One request's ASGI send, keeping the status and headers its response starts with."""

    def __init__(self, send: Send) -> None:
        self.send = send
        # A response that never starts counts as a server error
        self.status = 500
        self.headers: dict[bytes, bytes] = {}

    async def __call__(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            self.status = message["status"]
            self.headers = dict(message.get("headers", []))
        await self.send(message)


def setup_metrics(settings: Settings, logger: structlog.stdlib.BoundLogger) -> None:
    """Set up the global OpenTelemetry MeterProvider with OTLP exporter.

    This is the single initialization point for metrics export.  ``BaseMetrics``
    subclasses and ``MetricsMiddleware`` obtain meters via the global API
    (``opentelemetry.metrics.get_meter``), so this must run before them.
    When skipped (tests / missing endpoint), the default no-op provider is used.
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

    otlp_exporter = OTLPMetricExporter(
        endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
        insecure=settings.OTEL_EXPORTER_OTLP_ENDPOINT.startswith("http://"),
    )

    metric_reader = PeriodicExportingMetricReader(
        exporter=otlp_exporter,
        export_interval_millis=60000,
    )

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader],
    )

    metrics.set_meter_provider(meter_provider)
    create_system_metrics()

    logger.info("OpenTelemetry metrics configured with OTLP exporter")


# --8<-- [start:system_metrics]
def _observe_memory(_: CallbackOptions) -> list[Observation]:
    """Get current memory usage."""
    memory = psutil.virtual_memory()
    return [
        Observation(memory.used, {"type": "used"}),
        Observation(memory.available, {"type": "available"}),
        Observation(memory.percent, {"type": "percent"}),
    ]


def _observe_cpu(_: CallbackOptions) -> list[Observation]:
    """Get current CPU usage."""
    return [Observation(psutil.cpu_percent(interval=None))]


class _ProcessObserver:
    """Reports this process's metrics; it keeps one psutil.Process, since cpu_percent measures from its last call."""

    def __init__(self) -> None:
        self.process = psutil.Process(os.getpid())

    def observe(self, _: CallbackOptions) -> list[Observation]:
        mem = self.process.memory_info()
        return [
            Observation(mem.rss, {"type": "rss"}),
            Observation(mem.vms, {"type": "vms"}),
            Observation(self.process.cpu_percent(), {"type": "cpu"}),
            Observation(self.process.num_threads(), {"type": "threads"}),
        ]


def create_system_metrics() -> None:
    """Create system metrics collectors."""
    meter = metrics.get_meter(__name__)
    meter.create_observable_gauge(
        name="system_memory_bytes", callbacks=[_observe_memory], description="System memory usage", unit="bytes"
    )
    meter.create_observable_gauge(
        name="system_cpu_percent", callbacks=[_observe_cpu], description="System CPU usage percentage", unit="percent"
    )
    meter.create_observable_gauge(
        name="process_metrics",
        callbacks=[_ProcessObserver().observe],
        description="Process-level metrics",
        unit="mixed",
    )


# --8<-- [end:system_metrics]
