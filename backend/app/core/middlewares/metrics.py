import os
import re
import time

import psutil
from fastapi import FastAPI
from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.metrics import CallbackOptions, Observation
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import logger
from app.settings import get_settings


class MetricsMiddleware:
    """Middleware to collect HTTP metrics using OpenTelemetry."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.meter = metrics.get_meter(__name__)

        # Create metrics instruments
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

        # Time the request
        start_time = time.time()
        status_code = 500  # Default to error if not set
        response_content_length = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, response_content_length

            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = dict(message.get("headers", []))
                content_length_header = response_headers.get(b"content-length")
                if content_length_header:
                    response_content_length = int(content_length_header)

            await send(message)

        await self.app(scope, receive, send_wrapper)

        # Record metrics after response
        duration = time.time() - start_time

        labels = {"method": method, "path": path_template, "status": str(status_code)}

        self.request_counter.add(1, labels)
        self.request_duration.record(duration, labels)

        if response_content_length is not None:
            self.response_size.record(response_content_length, labels)

        # Decrement active requests
        self.active_requests.add(-1, {"method": method, "path": path_template})

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


def setup_metrics(app: FastAPI) -> None:
    """Set up OpenTelemetry metrics with OTLP exporter."""
    settings = get_settings()
    # Fast opt-out for tests or when explicitly disabled
    if settings.TESTING or os.getenv("OTEL_SDK_DISABLED", "").lower() in {"1", "true", "yes"}:
        logger.info("OpenTelemetry metrics disabled (TESTING/OTEL_SDK_DISABLED)")
        return

    # Configure OpenTelemetry resource
    resource = Resource.create(
        {
            SERVICE_NAME: settings.PROJECT_NAME,
            SERVICE_VERSION: "1.0.0",
            "service.environment": "test" if settings.TESTING else "production",
        }
    )

    # Configure OTLP exporter (sends to OpenTelemetry Collector or compatible backend)
    # Default endpoint is localhost:4317 for gRPC
    otlp_exporter = OTLPMetricExporter(
        endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317"),
        insecure=True,  # Use insecure for local development
    )

    # Create metric reader with 60 second export interval
    metric_reader = PeriodicExportingMetricReader(
        exporter=otlp_exporter,
        export_interval_millis=60000,
    )

    # Set up the meter provider
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader],
    )

    # Set the global meter provider
    metrics.set_meter_provider(meter_provider)

    # Create system metrics
    create_system_metrics()

    # Add the metrics middleware (disabled for now to avoid DNS issues)
    # app.add_middleware(MetricsMiddleware)

    logger.info("OpenTelemetry metrics configured with OTLP exporter")


def create_system_metrics() -> None:
    """Create system metrics collectors."""
    meter = metrics.get_meter(__name__)

    # Process for system metrics
    current_process = psutil.Process(os.getpid())

    # Memory usage
    def get_memory_usage(_: CallbackOptions) -> list[Observation]:
        """Get current memory usage."""
        memory = psutil.virtual_memory()
        return [
            Observation(memory.used, {"type": "used"}),
            Observation(memory.available, {"type": "available"}),
            Observation(memory.percent, {"type": "percent"}),
        ]

    meter.create_observable_gauge(
        name="system_memory_bytes", callbacks=[get_memory_usage], description="System memory usage", unit="bytes"
    )

    # CPU usage
    def get_cpu_usage(_: CallbackOptions) -> list[Observation]:
        """Get current CPU usage."""
        cpu_percent = psutil.cpu_percent(interval=1)
        return [Observation(cpu_percent)]

    meter.create_observable_gauge(
        name="system_cpu_percent", callbacks=[get_cpu_usage], description="System CPU usage percentage", unit="percent"
    )

    # Process metrics
    def get_process_metrics(_: CallbackOptions) -> list[Observation]:
        """Get current process metrics."""
        return [
            Observation(current_process.memory_info().rss, {"type": "rss"}),
            Observation(current_process.memory_info().vms, {"type": "vms"}),
            Observation(current_process.cpu_percent(), {"type": "cpu"}),
            Observation(current_process.num_threads(), {"type": "threads"}),
        ]

    meter.create_observable_gauge(
        name="process_metrics", callbacks=[get_process_metrics], description="Process-level metrics", unit="mixed"
    )
