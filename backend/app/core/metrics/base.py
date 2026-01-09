from dataclasses import dataclass

from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.metrics import Meter, NoOpMeterProvider
from opentelemetry.sdk.metrics import MeterProvider as SdkMeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

from app.settings import Settings


@dataclass
class MetricsConfig:
    service_name: str = "integr8scode-backend"
    service_version: str = "1.0.0"
    otlp_endpoint: str | None = None
    export_interval_millis: int = 10000
    console_export_interval_millis: int = 60000


class BaseMetrics:
    def __init__(self, settings: Settings, meter_name: str | None = None):
        """Initialize base metrics with its own meter.

        Args:
            settings: Application settings.
            meter_name: Optional name for the meter. Defaults to class name.
        """
        config = MetricsConfig(
            service_name=settings.TRACING_SERVICE_NAME or "integr8scode-backend",
            service_version="1.0.0",
            otlp_endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
        )

        meter_name = meter_name or self.__class__.__name__
        self._meter = self._create_meter(settings, config, meter_name)
        self._create_instruments()

    def _create_meter(self, settings: Settings, config: MetricsConfig, meter_name: str) -> Meter:
        """Create a new meter instance for this collector.

        Args:
            settings: Application settings
            config: Metrics configuration
            meter_name: Name for this meter

        Returns:
            A new meter instance
        """
        # If tracing/metrics disabled or no OTLP endpoint configured, use NoOp meter
        if not config.otlp_endpoint:
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
