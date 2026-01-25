from app.core.metrics.base import BaseMetrics


class RateLimitMetrics(BaseMetrics):
    """Metrics for rate limiting system."""

    def _create_instruments(self) -> None:
        self._requests = self._meter.create_counter(
            name="rate_limit.requests.total",
            description="Total number of rate limit checks",
            unit="1",
        )
        self._allowed = self._meter.create_counter(
            name="rate_limit.allowed.total",
            description="Number of allowed requests",
            unit="1",
        )
        self._rejected = self._meter.create_counter(
            name="rate_limit.rejected.total",
            description="Number of rejected requests",
            unit="1",
        )
        self._bypass = self._meter.create_counter(
            name="rate_limit.bypass.total",
            description="Number of bypassed rate limit checks",
            unit="1",
        )

    def record_request(self, endpoint: str, authenticated: bool, algorithm: str) -> None:
        """Record a rate limit check request."""
        attrs = {"endpoint": endpoint, "authenticated": str(authenticated).lower(), "algorithm": algorithm}
        self._requests.add(1, attrs)

    def record_allowed(self, endpoint: str, group: str) -> None:
        """Record an allowed request."""
        self._allowed.add(1, {"endpoint": endpoint, "group": group})

    def record_rejected(self, endpoint: str, group: str) -> None:
        """Record a rejected request."""
        self._rejected.add(1, {"endpoint": endpoint, "group": group})

    def record_bypass(self, endpoint: str) -> None:
        """Record a bypassed rate limit check."""
        self._bypass.add(1, {"endpoint": endpoint})
