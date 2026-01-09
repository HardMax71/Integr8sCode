from dataclasses import dataclass
from typing import Optional

from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.metrics import Meter, NoOpMeterProvider
from opentelemetry.sdk.metrics import MeterProvider as SdkMeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

from app.settings import get_settings


@dataclass
class MetricsConfig:
    service_name: str = "integr8scode-backend"
    service_version: str = "1.0.0"
    otlp_endpoint: Optional[str] = None
    export_interval_millis: int = 10000
    console_export_interval_millis: int = 60000


class BaseMetrics:
    def __init__(self, meter_name: str | None = None):
        """Initialize base metrics with its own meter.

        Args:
            meter_name: Optional name for the meter. Defaults to class name.
        """
        # Get settings and create config
        settings = get_settings()
        config = MetricsConfig(
            service_name=settings.TRACING_SERVICE_NAME or "integr8scode-backend",
            service_version="1.0.0",
            otlp_endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
        )

        # Each collector creates its own independent meter
        meter_name = meter_name or self.__class__.__name__
        self._meter = self._create_meter(config, meter_name)
        self._create_instruments()

    def _create_meter(self, config: MetricsConfig, meter_name: str) -> Meter:
        """Create a new meter instance for this collector.

        Args:
            config: Metrics configuration
            meter_name: Name for this meter

        Returns:
            A new meter instance
        """
        # If tracing/metrics disabled or no OTLP endpoint configured, use NoOp meter to avoid threads/network
        settings = get_settings()
        if settings.TESTING or not settings.ENABLE_TRACING or not config.otlp_endpoint:
            return NoOpMeterProvider().get_meter(meter_name)

        resource = Resource.create(
            {"service.name": config.service_name, "service.version": config.service_version, "meter.name": meter_name}
        )

        reader = PeriodicExportingMetricReader(
            exporter=OTLPMetricExporter(endpoint=config.otlp_endpoint),
            export_interval_millis=config.export_interval_millis,
        )

        # Each collector gets its own MeterProvider
        meter_provider = SdkMeterProvider(resource=resource, metric_readers=[reader])

        # Return a meter from this provider
        return meter_provider.get_meter(meter_name)

    def _create_instruments(self) -> None:
        """Create metric instruments. Override in subclasses."""
        pass

    def close(self) -> None:
        """Close the metrics collector and clean up resources."""
        # Subclasses can override if they need cleanup
        pass
