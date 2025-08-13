"""Kafka circuit breaker module with unified implementation."""
from app.events.kafka.cb.config import CircuitBreakerConfig
from app.events.kafka.cb.enums import CircuitState, CircuitStateStr
from app.events.kafka.cb.errors import CircuitBreakerError, CircuitBreakerOpenError
from app.events.kafka.cb.kafka_cb_manager import (
    KafkaCircuitBreakerFactory,
    KafkaCircuitBreakerManager,
    KafkaConsumerWithCircuitBreaker,
    KafkaProducerWithCircuitBreaker,
)
from app.events.kafka.cb.kafka_circuit_breaker import (
    CircuitBreakerType,
    KafkaCircuitBreaker,
)

# Alias for backward compatibility
CircuitBreaker = KafkaCircuitBreaker

__all__ = [
    # Core components
    "CircuitBreaker",  # Alias for KafkaCircuitBreaker
    "KafkaCircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    "CircuitStateStr",
    "CircuitBreakerError",
    "CircuitBreakerOpenError",
    # Types
    "CircuitBreakerType",
    # Manager and factories
    "KafkaCircuitBreakerManager",
    "KafkaCircuitBreakerFactory",
    "KafkaProducerWithCircuitBreaker",
    "KafkaConsumerWithCircuitBreaker",
]
