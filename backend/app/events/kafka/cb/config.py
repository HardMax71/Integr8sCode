from typing import List

from pydantic import BaseModel, Field


class CircuitBreakerConfig(BaseModel):
    """Configuration for circuit breaker"""
    # Failure thresholds
    failure_threshold: int = Field(default=5, ge=1, description="Failures before opening")
    failure_rate_threshold: float = Field(default=0.5, ge=0.0, le=1.0, description="Failure rate threshold")
    slow_call_duration_threshold: float = Field(default=60.0, gt=0, description="Slow call threshold in seconds")
    slow_call_rate_threshold: float = Field(default=0.5, ge=0.0, le=1.0, description="Slow call rate threshold")

    # Timing
    timeout: float = Field(default=60.0, gt=0, description="Call timeout in seconds")
    wait_duration_open: float = Field(default=60.0, gt=0, description="Time to wait in open state")

    # Half-open state
    permitted_calls_in_half_open: int = Field(default=3, ge=1, description="Test calls in half-open state")

    # Sliding window
    sliding_window_size: int = Field(default=100, ge=10, description="Size of sliding window")
    minimum_number_of_calls: int = Field(default=10, ge=1, description="Minimum calls before evaluation")

    # Recovery
    automatic_recovery: bool = Field(default=True, description="Enable automatic recovery")
    recovery_timeout: float = Field(default=30.0, gt=0, description="Recovery timeout in half-open state")

    # Monitoring
    record_exceptions: List[type] = Field(default_factory=list, description="Exceptions to record as failures")
    ignore_exceptions: List[type] = Field(default_factory=list, description="Exceptions to ignore")
