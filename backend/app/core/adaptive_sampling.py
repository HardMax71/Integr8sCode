import logging
import time
from collections import deque
from collections.abc import Sequence

from opentelemetry.context import Context
from opentelemetry.sdk.trace.sampling import Decision, Sampler, SamplingResult
from opentelemetry.trace import Link, SpanKind, TraceState, get_current_span
from opentelemetry.util.types import Attributes

from app.settings import Settings


class AdaptiveSampler(Sampler):
    """
    Adaptive sampler that adjusts sampling rate based on:
    - Error rate
    - Request rate
    - Resource utilization

    Rate adjustment is lazy: it runs inline during should_sample()
    when the adjustment interval has elapsed.
    """

    def __init__(
        self,
        base_rate: float = 0.1,
        min_rate: float = 0.01,
        max_rate: float = 1.0,
        error_rate_threshold: float = 0.05,
        high_traffic_threshold: int = 1000,
        adjustment_interval: int = 60,
    ):
        """
        Initialize adaptive sampler

        Args:
            base_rate: Base sampling rate (default 10%)
            min_rate: Minimum sampling rate (default 1%)
            max_rate: Maximum sampling rate (default 100%)
            error_rate_threshold: Error rate that triggers increased sampling (default 5%)
            high_traffic_threshold: Requests per minute to consider high traffic
            adjustment_interval: Seconds between rate adjustments
        """
        self.base_rate = base_rate
        self.min_rate = min_rate
        self.max_rate = max_rate
        self.error_rate_threshold = error_rate_threshold
        self.high_traffic_threshold = high_traffic_threshold
        self.adjustment_interval = adjustment_interval

        self._current_rate = base_rate
        self._last_adjustment = time.time()

        # Sliding window for rate calculation (1 minute window, pruned by _calculate_metrics)
        self._request_window: deque[float] = deque()
        self._error_window: deque[float] = deque()

        logging.getLogger("integr8scode").info(f"Adaptive sampler initialized with base rate: {base_rate}")

    def should_sample(
        self,
        parent_context: Context | None,
        trace_id: int,
        name: str,
        kind: SpanKind | None = None,
        attributes: Attributes | None = None,
        links: Sequence[Link] | None = None,
        trace_state: TraceState | None = None,
    ) -> SamplingResult:
        """Determine if a span should be sampled"""
        parent_span_context = get_current_span(parent_context).get_span_context()
        parent_trace_state = None

        # Always sample if parent was sampled
        if parent_span_context is not None and parent_span_context.is_valid:
            parent_trace_state = parent_span_context.trace_state
            if parent_span_context.trace_flags.sampled:
                if parent_trace_state is not None:
                    return SamplingResult(
                        decision=Decision.RECORD_AND_SAMPLE, attributes=attributes, trace_state=parent_trace_state
                    )
                else:
                    return SamplingResult(decision=Decision.RECORD_AND_SAMPLE, attributes=attributes)

        # Track request
        self._request_window.append(time.time())

        # Always sample errors
        if self._is_error(attributes):
            self._error_window.append(time.time())
            if parent_trace_state is not None:
                return SamplingResult(
                    decision=Decision.RECORD_AND_SAMPLE, attributes=attributes, trace_state=parent_trace_state
                )
            else:
                return SamplingResult(decision=Decision.RECORD_AND_SAMPLE, attributes=attributes)

        # Lazy adjustment: re-evaluate rate when interval has elapsed
        now = time.time()
        if now - self._last_adjustment >= self.adjustment_interval:
            self._last_adjustment = now
            self._adjust_sampling_rate()

        # Apply current sampling rate using trace ID for deterministic sampling
        max_trace_id = (1 << 64) - 1
        masked_trace_id = trace_id & max_trace_id
        threshold = int(self._current_rate * max_trace_id)
        if self._current_rate >= 1.0:
            threshold = max_trace_id
        should_sample = masked_trace_id < threshold

        if parent_trace_state is not None:
            return SamplingResult(
                decision=Decision.RECORD_AND_SAMPLE if should_sample else Decision.DROP,
                attributes=attributes if should_sample else None,
                trace_state=parent_trace_state,
            )
        else:
            return SamplingResult(
                decision=Decision.RECORD_AND_SAMPLE if should_sample else Decision.DROP,
                attributes=attributes if should_sample else None,
            )

    def get_description(self) -> str:
        """Return sampler description"""
        return f"AdaptiveSampler(current_rate={self._current_rate:.2%})"

    def _is_error(self, attributes: Attributes | None) -> bool:
        """Check if span attributes indicate an error"""
        if not attributes:
            return False

        if attributes.get("error", False):
            return True

        status_code = attributes.get("http.status_code")
        if status_code and isinstance(status_code, (int, float)):
            if int(status_code) >= 500:
                return True
        elif status_code and isinstance(status_code, str) and status_code.isdigit():
            if int(status_code) >= 500:
                return True

        if attributes.get("exception.type"):
            return True

        return False

    def _calculate_metrics(self) -> tuple[float, int]:
        """Calculate current error rate and request rate"""
        minute_ago = time.time() - 60

        while self._request_window and self._request_window[0] < minute_ago:
            self._request_window.popleft()
        while self._error_window and self._error_window[0] < minute_ago:
            self._error_window.popleft()

        request_rate = len(self._request_window)
        error_rate = len(self._error_window) / max(1, len(self._request_window))

        return error_rate, request_rate

    def _adjust_sampling_rate(self) -> None:
        """Adjust sampling rate based on current metrics"""
        error_rate, request_rate = self._calculate_metrics()

        new_rate = self.base_rate

        if error_rate > self.error_rate_threshold:
            error_multiplier: float = min(10.0, 1 + (error_rate / self.error_rate_threshold))
            new_rate = min(self.max_rate, self.base_rate * error_multiplier)
            logging.getLogger("integr8scode").warning(
                f"High error rate detected ({error_rate:.1%}), increasing sampling to {new_rate:.1%}"
            )
        elif request_rate > self.high_traffic_threshold:
            traffic_divisor = request_rate / self.high_traffic_threshold
            new_rate = max(self.min_rate, self.base_rate / traffic_divisor)
            logging.getLogger("integr8scode").info(
                f"High traffic detected ({request_rate} req/min), decreasing sampling to {new_rate:.1%}"
            )

        if new_rate != self._current_rate:
            change_rate = 0.5
            self._current_rate = self._current_rate + (new_rate - self._current_rate) * change_rate

            logging.getLogger("integr8scode").info(
                f"Adjusted sampling rate to {self._current_rate:.1%} "
                f"(error_rate: {error_rate:.1%}, request_rate: {request_rate} req/min)"
            )


def create_adaptive_sampler(settings: Settings) -> AdaptiveSampler:
    """Create adaptive sampler with settings"""
    return AdaptiveSampler(
        base_rate=settings.TRACING_SAMPLING_RATE,
        min_rate=max(0.001, settings.TRACING_SAMPLING_RATE / 100),
        max_rate=1.0,
        error_rate_threshold=0.05,
        high_traffic_threshold=1000,
        adjustment_interval=60,
    )
