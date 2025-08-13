"""Unified Kafka circuit breaker implementation."""
import asyncio
import time
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any, Awaitable, Callable, Optional, TypeVar, Union, cast

from app.core.logging import logger
from app.events.kafka.cb.config import CircuitBreakerConfig
from app.events.kafka.cb.enums import CircuitState
from app.events.kafka.cb.errors import CircuitBreakerOpenError
from app.events.kafka.metrics.metrics import (
    CIRCUIT_RECOVERIES,
    CIRCUIT_STATE,
    CIRCUIT_TRIPS,
)

T = TypeVar('T')


class CircuitBreakerType(Enum):
    """Type of circuit breaker for Kafka operations."""
    PRODUCER = auto()
    CONSUMER = auto()
    GENERAL = auto()  # For non-Kafka services like Kubernetes


class KafkaCircuitBreaker:
    """Unified circuit breaker for all services.
    
    This implementation combines the functionality of both the base CircuitBreaker
    and the Kafka-specific circuit breakers into a single, flexible class.
    """
    
    # Default configurations for different types
    DEFAULT_CONFIGS: dict[CircuitBreakerType, dict[str, int | float]] = {
        CircuitBreakerType.PRODUCER: {
            "failure_threshold": 10,
            "success_threshold": 5,
            "timeout": 30.0,
            "half_open_max_attempts": 3,
        },
        CircuitBreakerType.CONSUMER: {
            "failure_threshold": 5,
            "success_threshold": 3,
            "timeout": 60.0,
            "half_open_max_attempts": 5,
        },
        CircuitBreakerType.GENERAL: {
            "failure_threshold": 5,
            "success_threshold": 3,
            "timeout": 60.0,
            "half_open_max_attempts": 3,
        },
    }
    
    def __init__(
        self,
        service_name: str,
        breaker_type: Optional[CircuitBreakerType] = None,
        identifier: Optional[str] = None,
        config: Optional[CircuitBreakerConfig] = None,
        failure_threshold: Optional[int] = None,
        success_threshold: Optional[int] = None,
        timeout: Optional[float] = None,
        half_open_max_attempts: Optional[int] = None,
    ) -> None:
        """Initialize circuit breaker.
        
        Args:
            service_name: Name of the service (used directly for GENERAL type)
            breaker_type: Type of circuit breaker (defaults to GENERAL)
            identifier: Topic/consumer group (only for PRODUCER/CONSUMER types)
            config: Optional configuration object
            failure_threshold: Number of failures before opening
            success_threshold: Number of successes needed to close from half-open
            timeout: Time in seconds before transitioning from open to half-open
            half_open_max_attempts: Max attempts in half-open state before reopening
        """
        self.breaker_type = breaker_type or CircuitBreakerType.GENERAL
        self.identifier = identifier
        
        # Set service name based on type
        if self.breaker_type == CircuitBreakerType.GENERAL:
            self.service_name = service_name
        else:
            # For Kafka types, generate service name
            if not identifier:
                raise ValueError(f"identifier required for {self.breaker_type.name} type")
            prefix = "kafka-producer" if self.breaker_type == CircuitBreakerType.PRODUCER else "kafka-consumer"
            self.service_name = f"{prefix}-{identifier}"
        
        # Determine configuration values
        if config:
            self.failure_threshold = config.failure_threshold
            self.success_threshold = config.permitted_calls_in_half_open
            self.timeout = config.wait_duration_open
            self.half_open_max_attempts = config.permitted_calls_in_half_open
        else:
            # Use explicit parameters or defaults
            defaults = self.DEFAULT_CONFIGS[self.breaker_type]
            self.failure_threshold = failure_threshold or int(defaults["failure_threshold"])
            self.success_threshold = success_threshold or int(defaults["success_threshold"])
            self.timeout = timeout or float(defaults["timeout"])
            self.half_open_max_attempts = half_open_max_attempts or int(defaults["half_open_max_attempts"])
        
        # Internal state
        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_attempts: int = 0
        self._lock: asyncio.Lock = asyncio.Lock()
        
        # Update metric
        CIRCUIT_STATE.labels(service=self.service_name).set(self._state.value)
    
    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state
    
    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self._state == CircuitState.CLOSED
    
    @property
    def is_open(self) -> bool:
        """Check if circuit is open (failing)."""
        if self._state == CircuitState.OPEN:
            # Check if timeout has passed
            if self._should_attempt_reset():
                self._transition_to_half_open()
        return self._state == CircuitState.OPEN
    
    @property
    def is_half_open(self) -> bool:
        """Check if circuit is half-open (testing)."""
        return self._state == CircuitState.HALF_OPEN
    
    async def can_proceed(self) -> bool:
        """Check if operation can proceed based on circuit state.
        
        Returns:
            True if circuit is not open, False otherwise
        """
        # Check for state transition from open to half-open
        if self._state == CircuitState.OPEN and self._should_attempt_reset():
            self._transition_to_half_open()
        
        return self._state != CircuitState.OPEN
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset.
        
        Returns:
            True if timeout has elapsed since last failure
        """
        if self._last_failure_time is None:
            return False
        
        return time.time() - self._last_failure_time >= self.timeout
    
    async def call(
        self,
        func: Callable[..., Union[T, Awaitable[T]]],
        *args: Any,
        **kwargs: Any
    ) -> T:
        """Execute function with circuit breaker protection.
        
        Args:
            func: Function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
            
        Returns:
            Result of func execution
            
        Raises:
            CircuitBreakerOpenError: If circuit is open
            Exception: Any exception raised by func
        """
        async with self._lock:
            if self.is_open:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is open for {self.service_name}"
                )
            
            if self.is_half_open:
                if self._half_open_attempts >= self.half_open_max_attempts:
                    self._transition_to_open()
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker is open for {self.service_name}"
                    )
                self._half_open_attempts += 1
        
        try:
            # Execute function
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = await asyncio.to_thread(func, *args, **kwargs)
            
            # Record success
            await self.record_success()
            return cast(T, result)
            
        except Exception:
            # Record failure
            await self.record_failure()
            raise
    
    async def record_success(self) -> None:
        """Record successful operation."""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._transition_to_closed()
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0
    
    async def record_failure(self) -> None:
        """Record failed operation."""
        async with self._lock:
            self._last_failure_time = time.time()
            
            if self._state == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    self._transition_to_open()
            elif self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open state opens the circuit
                self._transition_to_open()
    
    def _transition_to_open(self) -> None:
        """Transition to open state."""
        logger.warning(f"Circuit breaker opened for {self.service_name}")
        self._state = CircuitState.OPEN
        self._failure_count = 0
        self._success_count = 0
        self._half_open_attempts = 0
        CIRCUIT_STATE.labels(service=self.service_name).set(self._state.value)
        CIRCUIT_TRIPS.labels(service=self.service_name).inc()
    
    def _transition_to_closed(self) -> None:
        """Transition to closed state."""
        logger.info(f"Circuit breaker closed for {self.service_name}")
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_attempts = 0
        CIRCUIT_STATE.labels(service=self.service_name).set(self._state.value)
        CIRCUIT_RECOVERIES.labels(service=self.service_name).inc()
    
    def _transition_to_half_open(self) -> None:
        """Transition to half-open state."""
        logger.info(f"Circuit breaker half-open for {self.service_name}")
        self._state = CircuitState.HALF_OPEN
        self._success_count = 0
        self._half_open_attempts = 0
        CIRCUIT_STATE.labels(service=self.service_name).set(self._state.value)
    
    async def reset(self) -> None:
        """Manually reset circuit breaker."""
        async with self._lock:
            self._transition_to_closed()
    
    async def open(self) -> None:
        """Manually open circuit breaker."""
        async with self._lock:
            self._transition_to_open()
    
    def get_status(self) -> dict[str, Any]:
        """Get circuit breaker status.
        
        Returns:
            Dictionary containing current status information
        """
        return {
            "service": self.service_name,
            "state": self._state.name,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure_time": (
                datetime.fromtimestamp(self._last_failure_time, tz=timezone.utc).isoformat()
                if self._last_failure_time else None
            ),
            "half_open_attempts": self._half_open_attempts,
        }
    
    @property
    def topic(self) -> Optional[str]:
        """Get topic name if this is a producer circuit breaker."""
        return self.identifier if self.breaker_type == CircuitBreakerType.PRODUCER else None
    
    @property
    def consumer_group(self) -> Optional[str]:
        """Get consumer group if this is a consumer circuit breaker."""
        return self.identifier if self.breaker_type == CircuitBreakerType.CONSUMER else None
