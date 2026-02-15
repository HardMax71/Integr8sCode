from opentelemetry import metrics

from app.settings import Settings


class BaseMetrics:
    # --8<-- [start:init]
    def __init__(self, settings: Settings, meter_name: str | None = None):
        """Initialize base metrics with a meter from the global MeterProvider.

        The global MeterProvider is configured once by ``setup_metrics``.
        If it hasn't been called (e.g. in tests), the default no-op provider is used.

        Args:
            settings: Application settings (kept for DI compatibility).
            meter_name: Optional name for the meter. Defaults to class name.
        """
        meter_name = meter_name or self.__class__.__name__
        self._meter = metrics.get_meter(meter_name)
        self._create_instruments()
    # --8<-- [end:init]

    def _create_instruments(self) -> None:
        """Create metric instruments. Override in subclasses."""
        pass

    def close(self) -> None:
        """Close the metrics collector and clean up resources."""
        pass
