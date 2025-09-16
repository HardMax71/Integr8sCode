from app.core.metrics.base import BaseMetrics


class RateLimitMetrics(BaseMetrics):
    """Metrics for rate limiting system."""

    def _create_instruments(self) -> None:
        # Request metrics
        self.requests_total = self._meter.create_counter(
            name="rate_limit.requests.total",
            description="Total number of rate limit checks",
            unit="1",
        )
        self.allowed = self._meter.create_counter(
            name="rate_limit.allowed.total",
            description="Number of allowed requests",
            unit="1",
        )
        self.rejected = self._meter.create_counter(
            name="rate_limit.rejected.total",
            description="Number of rejected requests",
            unit="1",
        )
        self.bypass = self._meter.create_counter(
            name="rate_limit.bypass.total",
            description="Number of bypassed rate limit checks",
            unit="1",
        )
        
        # Performance metrics
        self.check_duration = self._meter.create_histogram(
            name="rate_limit.check.duration",
            description="Duration of rate limit checks",
            unit="ms",
        )
        self.redis_duration = self._meter.create_histogram(
            name="rate_limit.redis.duration",
            description="Duration of Redis operations",
            unit="ms",
        )
        self.algorithm_duration = self._meter.create_histogram(
            name="rate_limit.algorithm.duration",
            description="Time to execute rate limit algorithm",
            unit="ms",
        )
        
        # Usage metrics
        self.remaining = self._meter.create_histogram(
            name="rate_limit.remaining",
            description="Remaining requests in rate limit window",
            unit="1",
        )
        self.quota_usage = self._meter.create_histogram(
            name="rate_limit.quota.usage",
            description="Percentage of quota used",
            unit="%",
        )
        self.window_size = self._meter.create_histogram(
            name="rate_limit.window.size",
            description="Size of rate limit window",
            unit="s",
        )
        
        # Configuration metrics - using histograms to record absolute values
        # We record the current value, and Grafana queries the latest
        self.active_rules = self._meter.create_histogram(
            name="rate_limit.active.rules",
            description="Number of active rate limit rules",
            unit="1",
        )
        self.custom_users = self._meter.create_histogram(
            name="rate_limit.custom.users",
            description="Number of users with custom rate limits",
            unit="1",
        )
        self.bypass_users = self._meter.create_histogram(
            name="rate_limit.bypass.users",
            description="Number of users with rate limit bypass",
            unit="1",
        )
        
        # Token bucket specific metrics
        self.token_bucket_tokens = self._meter.create_histogram(
            name="rate_limit.token_bucket.tokens",
            description="Current tokens in token bucket",
            unit="1",
        )
        self.token_bucket_refill_rate = self._meter.create_histogram(
            name="rate_limit.token_bucket.refill_rate",
            description="Token bucket refill rate",
            unit="tokens/s",
        )
        
        # Error metrics
        self.redis_errors = self._meter.create_counter(
            name="rate_limit.redis.errors.total",
            description="Number of Redis errors",
            unit="1",
        )
        self.config_errors = self._meter.create_counter(
            name="rate_limit.config.errors.total",
            description="Number of configuration load errors",
            unit="1",
        )
        
        # Authenticated vs anonymous checks can be derived from labels on requests_total
        # No separate ip/user counters to avoid duplication and complexity.
