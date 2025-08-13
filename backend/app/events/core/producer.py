"""
Unified Kafka producer with Avro schema registry support.

This module provides a high-performance, async Kafka producer that handles both
Avro-based events and regular dictionaries with automatic serialization.

Features:
- Native async support with aiokafka
- Avro schema registry integration
- Circuit breaker per topic
- Dead Letter Queue (DLQ) support
- Retry mechanism with exponential backoff
- OpenTelemetry tracing
- Type-safe with Python 3.12+ features
"""

import asyncio
import json
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, TypeAlias, TypeVar

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError
from confluent_kafka import Producer as ConfluentProducer
from confluent_kafka.serialization import MessageField, SerializationContext, StringSerializer
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.config import get_settings
from app.core.logging import logger
from app.events.kafka.cb import (
    CircuitBreakerOpenError,
    CircuitBreakerType,
    KafkaCircuitBreaker,
    KafkaCircuitBreakerManager,
)
from app.events.kafka.metrics.metrics import (
    KAFKA_MESSAGES_FAILED,
    KAFKA_MESSAGES_SENT,
    KAFKA_SEND_DURATION,
)
from app.events.schema.schema_registry import get_schema_registry
from app.schemas_avro.event_schemas import BaseEvent as AvroBaseEvent

# Type aliases
EventData: TypeAlias = dict[str, Any]
Headers: TypeAlias = dict[str, str | bytes]
ProducerCallback: TypeAlias = Callable[[Exception | None, Any], None]
EventType = TypeVar("EventType", AvroBaseEvent, dict[str, Any])


class ProducerError(Exception):
    """Base exception for producer operations."""
    pass


class SerializationError(ProducerError):
    """Raised when message serialization fails."""
    pass


class DeliveryError(ProducerError):
    """Raised when message delivery fails."""
    pass


class CompressionType(StrEnum):
    """Kafka compression types."""
    NONE = "none"
    GZIP = "gzip"
    SNAPPY = "snappy"
    LZ4 = "lz4"
    ZSTD = "zstd"


@dataclass(frozen=True, slots=True)
class ProducerConfig:
    """Configuration for unified Kafka producer."""
    bootstrap_servers: str
    schema_registry_url: str
    client_id: str = "integr8scode-producer"
    compression_type: CompressionType = CompressionType.GZIP
    batch_size: int = 16384
    linger_ms: int = 10
    request_timeout_ms: int = 30000
    max_retries: int = 3
    retry_backoff_ms: int = 100
    enable_idempotence: bool = True
    dlq_topic: str = "dead-letter-queue"
    dlq_enabled: bool = True

    def to_aiokafka_config(self) -> dict[str, Any]:
        """Convert to aiokafka configuration."""
        return {
            "bootstrap_servers": self.bootstrap_servers,
            "client_id": self.client_id,
            "compression_type": self.compression_type,
            "max_batch_size": self.batch_size,  # AIOKafkaProducer uses max_batch_size
            "linger_ms": self.linger_ms,
            "request_timeout_ms": self.request_timeout_ms,
            "max_request_size": 1048576,  # 1MB default
            "metadata_max_age_ms": 300000,  # 5 minutes
            "retry_backoff_ms": self.retry_backoff_ms,
            "enable_idempotence": self.enable_idempotence,
            "key_serializer": lambda k: k.encode("utf-8") if isinstance(k, str) else k,
            "value_serializer": lambda v: v,  # We handle serialization ourselves
        }


@dataclass(frozen=True, slots=True)
class DeliveryReport:
    """Report of message delivery status."""
    topic: str
    partition: int
    offset: int
    timestamp: datetime
    latency_ms: float
    error: Exception | None = None


class UnifiedProducer:
    """
    Unified async Kafka producer supporting both Avro and dict events.
    
    This producer automatically detects event types and applies appropriate
    serialization without branching or magic methods.
    """

    def __init__(self, config: ProducerConfig) -> None:
        self.config = config
        self._producer: AIOKafkaProducer | None = None
        self._dlq_producer: ConfluentProducer | None = None
        self._schema_registry_manager = get_schema_registry()
        self._circuit_breaker_manager = KafkaCircuitBreakerManager()
        self._circuit_breakers: dict[str, KafkaCircuitBreaker] = {}
        self._running = False
        self._failed_queue: asyncio.Queue[tuple[str, bytes, bytes | None, Headers | None]] = asyncio.Queue(
            maxsize=10000)
        self._retry_task: asyncio.Task[None] | None = None
        self._metrics_task: asyncio.Task[None] | None = None
        self._string_serializer = StringSerializer("utf-8")

    async def start(self) -> None:
        """Start the producer and background tasks."""
        if self._running:
            return

        logger.info("Starting unified Kafka producer")

        # Initialize main producer
        self._producer = AIOKafkaProducer(**self.config.to_aiokafka_config())
        await self._producer.start()

        # Initialize DLQ producer if enabled
        if self.config.dlq_enabled:
            self._dlq_producer = ConfluentProducer({
                "bootstrap.servers": self.config.bootstrap_servers,
                "client.id": f"{self.config.client_id}-dlq"
            })

        # Start background tasks
        self._running = True
        self._retry_task = asyncio.create_task(self._retry_failed_events())
        self._metrics_task = asyncio.create_task(self._collect_metrics())

        logger.info("Unified Kafka producer started successfully")

    async def stop(self) -> None:
        """Stop the producer and cleanup resources."""
        if not self._running:
            return

        logger.info("Stopping unified Kafka producer")
        self._running = False

        # Cancel background tasks
        if self._retry_task:
            self._retry_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._retry_task

        if self._metrics_task:
            self._metrics_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._metrics_task

        # Stop producers
        if self._producer:
            await self._producer.stop()

        if self._dlq_producer:
            self._dlq_producer.flush(10)

        logger.info("Unified Kafka producer stopped")

    async def send_event(
            self,
            event: AvroBaseEvent | dict[str, Any],
            topic: str,
            key: str | None = None,
            headers: Headers | None = None,
            callback: ProducerCallback | None = None,
    ) -> DeliveryReport:
        """
        Send an event to Kafka.
        
        Args:
            event: Avro event object or dictionary
            topic: Kafka topic name
            key: Message key (optional)
            headers: Message headers (optional)
            callback: Delivery callback (optional)
            
        Returns:
            DeliveryReport with send details
            
        Raises:
            SerializationError: If event serialization fails
            DeliveryError: If delivery fails after retries
            CircuitBreakerOpenError: If circuit breaker is open
        """
        if not self._producer:
            raise ProducerError("Producer not started")

        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("kafka_send_event") as span:
            span.set_attribute("messaging.system", "kafka")
            span.set_attribute("messaging.destination", topic)
            span.set_attribute("messaging.destination_kind", "topic")

            # Get circuit breaker for topic
            circuit_breaker = await self._get_circuit_breaker(topic)
            if not await circuit_breaker.can_proceed():
                raise CircuitBreakerOpenError(f"Circuit breaker open for topic {topic}")

            try:
                # Serialize event
                serialized_value = await self._serialize_event(event, topic)
                serialized_key = self._serialize_key(key) if key else None

                # Prepare headers
                final_headers = self._prepare_headers(headers, span)

                # Send to Kafka
                send_start = asyncio.get_event_loop().time()
                future = await self._producer.send(
                    topic=topic,
                    value=serialized_value,
                    key=serialized_key,
                    headers=final_headers if final_headers else None,
                )

                # Wait for confirmation
                record = await future
                send_duration = asyncio.get_event_loop().time() - send_start

                # Record success
                await circuit_breaker.record_success()
                KAFKA_MESSAGES_SENT.labels(topic=topic).inc()
                KAFKA_SEND_DURATION.labels(topic=topic).observe(send_duration)

                # Create delivery report
                report = DeliveryReport(
                    topic=record.topic,
                    partition=record.partition,
                    offset=record.offset,
                    timestamp=datetime.now(timezone.utc),
                    latency_ms=send_duration * 1000,
                )

                # Execute callback if provided
                if callback:
                    asyncio.create_task(self._execute_callback(callback, None, report))

                span.set_status(Status(StatusCode.OK))
                return report

            except Exception as e:
                await circuit_breaker.record_failure()
                KAFKA_MESSAGES_FAILED.labels(topic=topic, error_type=type(e).__name__).inc()

                # Add to retry queue if retriable
                if self._is_retriable_error(e) and self.config.dlq_enabled:
                    # Convert headers back to dict for retry queue
                    headers_dict = None
                    if final_headers:
                        headers_dict = {k: v.decode('utf-8') if isinstance(v, bytes) else v for k, v in final_headers}
                    await self._add_to_retry_queue(topic, serialized_value, serialized_key, headers_dict)

                # Execute error callback
                if callback:
                    asyncio.create_task(self._execute_callback(callback, e, None))

                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise DeliveryError(f"Failed to send event to {topic}: {e}") from e

    async def send_batch(
            self,
            events: list[tuple[AvroBaseEvent | dict[str, Any], str, str | None]],
            ordered: bool = True,
    ) -> list[DeliveryReport | Exception]:
        """
        Send multiple events in batch.
        
        Args:
            events: List of (event, topic, key) tuples
            ordered: Whether to maintain order (sequential) or send in parallel
            
        Returns:
            List of DeliveryReports or Exceptions for each event
        """
        if ordered:
            results: list[DeliveryReport | Exception] = []
            for event, topic, key in events:
                try:
                    result = await self.send_event(event, topic, key)
                    results.append(result)
                except Exception as e:
                    results.append(e)
            return results
        else:
            # Parallel sending
            tasks = [
                self.send_event(event, topic, key)
                for event, topic, key in events
            ]
            gathered_results = await asyncio.gather(*tasks, return_exceptions=True)
            return [r if isinstance(r, (DeliveryReport, Exception))
                    else Exception(f"Unexpected result type: {type(r)}") for r in gathered_results]

    async def _serialize_event(
            self,
            event: AvroBaseEvent | dict[str, Any],
            topic: str
    ) -> bytes:
        """Serialize event based on its type."""
        # Use schema registry for Avro events
        if isinstance(event, AvroBaseEvent):
            return self._schema_registry_manager.serialize_event(event, topic)
        else:
            # Use JSON serialization for plain dicts
            return json.dumps(event).encode("utf-8")

    def _serialize_key(self, key: str) -> bytes:
        result = self._string_serializer(
            key,
            SerializationContext("", MessageField.KEY)
        )
        if not isinstance(result, bytes):
            raise TypeError(f"String serializer returned {type(result)} instead of bytes")
        return result

    def _prepare_headers(
            self,
            headers: Headers | None,
            span: Any
    ) -> list[tuple[str, bytes]]:
        """Prepare message headers with trace context.
        
        Returns headers as list of tuples with bytes values as required by aiokafka.
        """
        final_headers = headers.copy() if headers else {}

        # Add trace context
        span_context = span.get_span_context()
        if span_context.is_valid:
            final_headers["trace_id"] = f"{span_context.trace_id:032x}"
            final_headers["span_id"] = f"{span_context.span_id:016x}"

        # Convert header values to bytes
        return [(k, v.encode('utf-8') if isinstance(v, str) else v) for k, v in final_headers.items()]

    async def _get_circuit_breaker(self, topic: str) -> KafkaCircuitBreaker:
        """Get or create circuit breaker for topic."""
        if topic not in self._circuit_breakers:
            self._circuit_breakers[topic] = await self._circuit_breaker_manager.get_or_create_breaker(
                CircuitBreakerType.PRODUCER,
                topic,
            )
        return self._circuit_breakers[topic]


    def _is_retriable_error(self, error: Exception) -> bool:
        """Check if error is retriable."""
        retriable_errors = (
            asyncio.TimeoutError,
            KafkaError,
        )
        return isinstance(error, retriable_errors)

    async def _add_to_retry_queue(
            self,
            topic: str,
            value: bytes,
            key: bytes | None,
            headers: Headers | None
    ) -> None:
        """Add failed message to retry queue."""
        try:
            await self._failed_queue.put((topic, value, key, headers))
        except asyncio.QueueFull:
            logger.error(f"Retry queue full, sending to DLQ: {topic}")
            await self._send_to_dlq(topic, value, key, headers, "retry_queue_full")

    async def _send_to_dlq(
            self,
            topic: str,
            value: bytes,
            key: bytes | None,
            headers: Headers | None,
            reason: str
    ) -> None:
        """Send failed message to Dead Letter Queue."""
        if not self._dlq_producer:
            return

        dlq_headers = headers.copy() if headers else {}
        dlq_headers.update({
            "original_topic": topic,
            "failure_reason": reason,
            "failure_timestamp": datetime.now(timezone.utc).isoformat(),
        })

        def delivery_callback(err: Any, msg: Any) -> None:
            if err:
                logger.error(f"Failed to send to DLQ: {err}")
            else:
                logger.info(f"Message sent to DLQ: {msg.topic()}")

        self._dlq_producer.produce(
            topic=self.config.dlq_topic,
            value=value,
            key=key,
            headers=list(dlq_headers.items()),
            callback=delivery_callback,
        )
        self._dlq_producer.poll(0)

    async def _retry_failed_events(self) -> None:
        """Background task to retry failed events."""
        while self._running:
            try:
                # Get failed event from queue
                topic, value, key, headers = await asyncio.wait_for(
                    self._failed_queue.get(),
                    timeout=5.0
                )

                # Exponential backoff
                for attempt in range(self.config.max_retries):
                    try:
                        await asyncio.sleep(self.config.retry_backoff_ms * (2 ** attempt) / 1000)

                        if self._producer:
                            await self._producer.send(
                                topic=topic,
                                value=value,
                                key=key,
                                headers=list(headers.items()) if headers else None,
                            )
                            logger.info(f"Successfully retried event to {topic}")
                            break
                    except Exception as e:
                        if attempt == self.config.max_retries - 1:
                            logger.error(f"Max retries exceeded for {topic}: {e}")
                            await self._send_to_dlq(topic, value, key, headers, str(e))

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in retry task: {e}")

    async def _collect_metrics(self) -> None:
        """Background task to collect producer metrics."""
        while self._running:
            try:
                await asyncio.sleep(30)  # Collect every 30 seconds

                if self._producer:
                    # Collect basic metrics (aiokafka doesn't expose detailed stats)
                    logger.debug("Metrics collection running")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error collecting metrics: {e}")

    async def _execute_callback(
            self,
            callback: ProducerCallback,
            error: Exception | None,
            report: DeliveryReport | None
    ) -> None:
        """Execute callback in background."""
        try:
            callback(error, report)
        except Exception as e:
            logger.error(f"Error in delivery callback: {e}")

    def get_status(self) -> dict[str, Any]:
        """
        Get current producer status.
        
        Returns:
            Dictionary with producer health metrics
        """
        return {
            "connected": self._running,
            "bootstrap_servers": self.config.bootstrap_servers,
            "retry_queue_size": self._failed_queue.qsize(),
            "circuit_breaker": self._get_circuit_breaker_summary(),
        }

    def _get_circuit_breaker_summary(self) -> dict[str, Any]:
        """Get aggregated circuit breaker status."""
        if not self._circuit_breakers:
            return {"state": "closed", "topics": 0}

        states = [cb.get_status() for cb in self._circuit_breakers.values()]
        open_count = sum(1 for s in states if s["state"] == "OPEN")

        return {
            "state": "open" if open_count > 0 else "closed",
            "open_topics": open_count,
            "total_topics": len(self._circuit_breakers),
        }

    async def __aenter__(self) -> "UnifiedProducer":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.stop()


class ProducerSingleton:
    """
    Singleton manager for UnifiedProducer instances.
    
    This class ensures only one producer instance exists per configuration
    and provides thread-safe access without using global variables.
    """

    def __init__(self) -> None:
        self._instances: dict[str, UnifiedProducer] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._main_lock = asyncio.Lock()

    async def get_producer(self, config_key: str = "default") -> UnifiedProducer:
        """
        Get or create a producer instance for the given configuration key.
        
        Args:
            config_key: Configuration identifier (default: "default")
            
        Returns:
            Initialized UnifiedProducer instance
        """
        # Fast path - check if instance exists
        if config_key in self._instances:
            return self._instances[config_key]

        # Get or create lock for this config
        async with self._main_lock:
            if config_key not in self._locks:
                self._locks[config_key] = asyncio.Lock()

        # Create instance with double-check pattern
        async with self._locks[config_key]:
            if config_key in self._instances:
                return self._instances[config_key]

            # Create new instance
            settings = get_settings()
            config = ProducerConfig(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                schema_registry_url=settings.SCHEMA_REGISTRY_URL,
                client_id=f"integr8scode-producer-{config_key}",
                dlq_topic=settings.KAFKA_DLQ_TOPIC,
                dlq_enabled=True,
            )

            producer = UnifiedProducer(config)
            await producer.start()

            self._instances[config_key] = producer
            return producer

    async def close_producer(self, config_key: str = "default") -> None:
        """
        Close and remove a specific producer instance.
        
        Args:
            config_key: Configuration identifier to close
        """
        if config_key not in self._instances:
            return

        async with self._locks.get(config_key, self._main_lock):
            if config_key in self._instances:
                await self._instances[config_key].stop()
                del self._instances[config_key]

    async def close_all(self) -> None:
        """
        Close all producer instances.
        """
        async with self._main_lock:
            for producer in self._instances.values():
                await producer.stop()
            self._instances.clear()
            self._locks.clear()


class _ProducerManager:
    """
    Internal class to manage the singleton instance without globals.
    """
    _instance: ProducerSingleton | None = None
    _lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    async def get_instance(cls) -> ProducerSingleton:
        """
        Get or create the singleton instance.
        """
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = ProducerSingleton()
        return cls._instance

    @classmethod
    async def reset(cls) -> None:
        """
        Reset the singleton instance (mainly for testing).
        """
        async with cls._lock:
            if cls._instance:
                await cls._instance.close_all()
            cls._instance = None


# Public API functions
async def get_producer() -> UnifiedProducer:
    """
    Get the default producer instance.
    
    Returns:
        Initialized UnifiedProducer instance
    """
    singleton = await _ProducerManager.get_instance()
    return await singleton.get_producer()


async def close_producer() -> None:
    """
    Close the default producer instance.
    """
    singleton = await _ProducerManager.get_instance()
    await singleton.close_producer()


async def get_producer_singleton() -> ProducerSingleton:
    """
    Get the ProducerSingleton instance for advanced usage.
    
    This allows creating multiple producer instances with different
    configurations if needed.
    
    Returns:
        The ProducerSingleton instance
    """
    return await _ProducerManager.get_instance()
