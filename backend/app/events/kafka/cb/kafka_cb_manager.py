"""Kafka circuit breaker manager without singleton pattern."""
import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable, Optional, cast

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from app.core.logging import logger
from app.events.kafka.cb.config import CircuitBreakerConfig
from app.events.kafka.cb.errors import CircuitBreakerOpenError
from app.events.kafka.cb.kafka_circuit_breaker import (
    CircuitBreakerType,
    KafkaCircuitBreaker,
)
from app.events.kafka.metrics.metrics_collector import (
    KAFKA_CIRCUIT_BREAKER_FALLBACKS,
    KAFKA_CIRCUIT_BREAKER_RECOVERY,
)
from app.schemas_avro.event_schemas import BaseEvent


class KafkaCircuitBreakerManager:
    """Manages Kafka circuit breakers without singleton pattern.
    
    This class should be instantiated once and passed via dependency injection.
    """

    def __init__(self, default_config: Optional[CircuitBreakerConfig] = None) -> None:
        """Initialize the circuit breaker manager.
        
        Args:
            default_config: Default configuration for new circuit breakers
        """
        self._default_config = default_config
        self._circuit_breakers: dict[str, KafkaCircuitBreaker] = {}
        self._lock = asyncio.Lock()

    async def get_or_create_breaker(
            self,
            breaker_type: CircuitBreakerType,
            identifier: str,
            config: Optional[CircuitBreakerConfig] = None,
    ) -> KafkaCircuitBreaker:
        """Get existing or create new circuit breaker.
        
        Args:
            breaker_type: Type of circuit breaker (producer/consumer)
            identifier: Topic name for producers, consumer group for consumers
            config: Optional configuration, uses default if not provided
            
        Returns:
            KafkaCircuitBreaker instance
        """
        key = f"{breaker_type.name}:{identifier}"

        async with self._lock:
            if key not in self._circuit_breakers:
                self._circuit_breakers[key] = KafkaCircuitBreaker(
                    service_name=identifier,  # Use identifier as service name
                    breaker_type=breaker_type,
                    identifier=identifier,
                    config=config or self._default_config,
                )

            return self._circuit_breakers[key]

    async def get_all_status(self) -> list[dict[str, Any]]:
        """Get status of all circuit breakers.
        
        Returns:
            List of status dictionaries
        """
        async with self._lock:
            return [cb.get_status() for cb in self._circuit_breakers.values()]

    async def reset_all(self) -> None:
        """Reset all circuit breakers to closed state."""
        async with self._lock:
            for cb in self._circuit_breakers.values():
                await cb.reset()

    async def clear(self) -> None:
        """Remove all circuit breakers."""
        async with self._lock:
            self._circuit_breakers.clear()


class KafkaProducerWithCircuitBreaker:
    """Enhanced Kafka producer with circuit breaker protection."""

    def __init__(
            self,
            producer: AIOKafkaProducer,
            manager: KafkaCircuitBreakerManager,
            fallback_queue_size: int = 10000,
    ) -> None:
        """Initialize producer with circuit breaker.
        
        Args:
            producer: Underlying Kafka producer
            manager: Circuit breaker manager instance
            fallback_queue_size: Maximum size of fallback queue
        """
        self._producer = producer
        self._manager = manager
        self._fallback_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=fallback_queue_size
        )
        self._recovery_task: Optional[asyncio.Task[None]] = None
        self._closed = False

    async def send_event(
            self,
            event: BaseEvent,
            topic: str,
            key: Optional[bytes] = None,
            headers: Optional[list[tuple[str, bytes]]] = None,
    ) -> bool:
        """Send event with circuit breaker protection.
        
        Args:
            event: Event to send
            topic: Kafka topic
            key: Optional message key
            headers: Optional headers
            
        Returns:
            True if sent or queued, False if dropped
        """
        # Get circuit breaker for this topic
        circuit_breaker = await self._manager.get_or_create_breaker(
            CircuitBreakerType.PRODUCER, topic
        )

        # Check if we can proceed
        if not await circuit_breaker.can_proceed():
            logger.warning(f"Circuit breaker open for topic {topic}, using fallback")
            KAFKA_CIRCUIT_BREAKER_FALLBACKS.labels(
                operation="produce", topic=topic
            ).inc()

            # Queue for later delivery
            return await self._queue_for_fallback(event, topic, key, headers)

        try:
            # Send through circuit breaker
            func = cast(Callable[..., Awaitable[Any]], self._send_to_kafka)
            await circuit_breaker.call(
                func, event, topic, key, headers
            )
            return True

        except CircuitBreakerOpenError:
            # Circuit opened during call, use fallback
            return await self._queue_for_fallback(event, topic, key, headers)

        except Exception as e:
            logger.error(f"Failed to send event to Kafka: {e}")
            await circuit_breaker.record_failure()
            return False

    async def _send_to_kafka(
            self,
            event: BaseEvent,
            topic: str,
            key: Optional[bytes],
            headers: Optional[list[tuple[str, bytes]]],
    ) -> None:
        """Internal method to send to Kafka."""
        value = event.model_dump_json().encode('utf-8')

        await self._producer.send_and_wait(
            topic=topic,
            value=value,
            key=key,
            headers=headers or [],
        )

    async def _queue_for_fallback(
            self,
            event: BaseEvent,
            topic: str,
            key: Optional[bytes],
            headers: Optional[list[tuple[str, bytes]]],
    ) -> bool:
        """Queue message for fallback delivery.
        
        Returns:
            True if queued, False if queue full
        """
        try:
            self._fallback_queue.put_nowait({
                "event": event,
                "topic": topic,
                "key": key,
                "headers": headers,
            })

            # Start recovery task if needed
            if not self._recovery_task or self._recovery_task.done():
                self._recovery_task = asyncio.create_task(
                    self._process_fallback_queue()
                )

            return True

        except asyncio.QueueFull:
            logger.error("Fallback queue full, message dropped")
            return False

    async def _process_fallback_queue(self) -> None:
        """Process messages from fallback queue when circuit recovers."""
        recovery_start = asyncio.get_event_loop().time()
        processed = 0

        while not self._closed and not self._fallback_queue.empty():
            # Get all messages for batch processing
            messages: list[dict[str, Any]] = []
            while not self._fallback_queue.empty() and len(messages) < 100:
                try:
                    messages.append(self._fallback_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            if not messages:
                break

            # Group by topic for efficient processing
            by_topic: dict[str, list[dict[str, Any]]] = {}
            for msg in messages:
                topic = msg["topic"]
                if topic not in by_topic:
                    by_topic[topic] = []
                by_topic[topic].append(msg)

            # Process each topic
            for topic, topic_messages in by_topic.items():
                circuit_breaker = await self._manager.get_or_create_breaker(
                    CircuitBreakerType.PRODUCER, topic
                )

                # Wait for circuit to recover
                while not await circuit_breaker.can_proceed():
                    if self._closed:
                        return
                    await asyncio.sleep(5)

                # Send messages
                for msg in topic_messages:
                    try:
                        func = cast(Callable[..., Awaitable[Any]], self._send_to_kafka)
                        await circuit_breaker.call(
                            func,
                            msg["event"],
                            msg["topic"],
                            msg["key"],
                            msg["headers"],
                        )
                        processed += 1

                    except Exception as e:
                        logger.error(f"Failed to send fallback message: {e}")
                        # Re-queue if possible
                        try:
                            self._fallback_queue.put_nowait(msg)
                        except asyncio.QueueFull:
                            logger.error("Cannot requeue failed message")

        # Record recovery metrics
        recovery_time = asyncio.get_event_loop().time() - recovery_start
        KAFKA_CIRCUIT_BREAKER_RECOVERY.labels(operation="produce").observe(
            recovery_time
        )

        logger.info(
            f"Fallback queue processed: {processed} messages in {recovery_time:.2f}s"
        )

    async def close(self) -> None:
        """Close producer and process remaining messages."""
        self._closed = True

        if self._recovery_task and not self._recovery_task.done():
            await self._recovery_task

        await self._producer.stop()


class KafkaConsumerWithCircuitBreaker:
    """Enhanced Kafka consumer with circuit breaker protection."""

    def __init__(
            self,
            consumer: AIOKafkaConsumer,
            manager: KafkaCircuitBreakerManager,
    ) -> None:
        """Initialize consumer with circuit breaker.
        
        Args:
            consumer: Underlying Kafka consumer
            manager: Circuit breaker manager instance
        """
        self._consumer = consumer
        self._manager = manager
        self._is_paused = False
        self._consumer_group = consumer._group_id

    async def consume_messages(
            self, max_records: int = 100, timeout_ms: int = 1000
    ) -> AsyncGenerator[Any, None]:
        """Consume messages with circuit breaker protection.
        
        Args:
            max_records: Maximum records to fetch per batch
            timeout_ms: Timeout for fetching messages
            
        Yields:
            Kafka messages
        """
        circuit_breaker = await self._manager.get_or_create_breaker(
            CircuitBreakerType.CONSUMER, self._consumer_group
        )

        while True:
            # Check circuit state and pause/resume as needed
            can_proceed = await circuit_breaker.can_proceed()

            if not can_proceed and not self._is_paused:
                logger.warning("Pausing consumer due to open circuit breaker")
                await self._consumer.pause(*self._consumer.assignment())
                self._is_paused = True
                KAFKA_CIRCUIT_BREAKER_FALLBACKS.labels(
                    operation="consume", topic="all"
                ).inc()

            elif can_proceed and self._is_paused:
                logger.info("Resuming consumer after circuit breaker recovery")
                await self._consumer.resume(*self._consumer.assignment())
                self._is_paused = False

            if not can_proceed:
                # Wait before retry
                await asyncio.sleep(5)
                continue

            try:
                # Fetch messages through circuit breaker
                messages: list[Any] = await circuit_breaker.call(
                    self._fetch_messages, max_records, timeout_ms
                )  # type: ignore[arg-type]

                for msg in messages:
                    yield msg

            except CircuitBreakerOpenError:
                logger.warning("Circuit breaker opened for consumer")
                await asyncio.sleep(5)

            except Exception as e:
                logger.error(f"Error consuming messages: {e}")
                await circuit_breaker.record_failure()
                await asyncio.sleep(1)

    async def _fetch_messages(
            self, max_records: int, timeout_ms: int
    ) -> list[Any]:
        """Internal method to fetch messages from Kafka."""
        messages = []

        records = await self._consumer.getmany(
            timeout_ms=timeout_ms, max_records=max_records
        )

        for _topic_partition, msgs in records.items():
            messages.extend(msgs)

        return messages

    async def commit_with_circuit_breaker(
            self, offsets: Optional[dict[Any, Any]] = None
    ) -> None:
        """Commit offsets with circuit breaker protection.
        
        Args:
            offsets: Optional specific offsets to commit
            
        Raises:
            CircuitBreakerOpenError: If circuit is open
        """
        circuit_breaker = await self._manager.get_or_create_breaker(
            CircuitBreakerType.CONSUMER, self._consumer_group
        )

        if not await circuit_breaker.can_proceed():
            raise CircuitBreakerOpenError(
                f"Cannot commit offsets, circuit breaker is open for {self._consumer_group}"
            )

        try:
            await circuit_breaker.call(self._consumer.commit, offsets)
        except Exception as e:
            logger.error(f"Failed to commit offsets: {e}")
            await circuit_breaker.record_failure()
            raise

    async def close(self) -> None:
        """Close consumer."""
        await self._consumer.stop()


class KafkaCircuitBreakerFactory:
    """Factory for creating Kafka clients with circuit breakers."""

    def __init__(self, manager: KafkaCircuitBreakerManager) -> None:
        """Initialize factory with circuit breaker manager.
        
        Args:
            manager: Circuit breaker manager instance
        """
        self._manager = manager

    @asynccontextmanager
    async def create_producer(
            self,
            bootstrap_servers: str,
            **producer_kwargs: Any,
    ) -> AsyncGenerator[KafkaProducerWithCircuitBreaker, None]:
        """Create Kafka producer with circuit breaker.
        
        Args:
            bootstrap_servers: Kafka bootstrap servers
            **producer_kwargs: Additional producer configuration
            
        Yields:
            KafkaProducerWithCircuitBreaker instance
        """
        producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            **producer_kwargs,
        )

        await producer.start()
        wrapped_producer = KafkaProducerWithCircuitBreaker(
            producer, self._manager
        )

        try:
            yield wrapped_producer
        finally:
            await wrapped_producer.close()

    @asynccontextmanager
    async def create_consumer(
            self,
            *topics: str,
            bootstrap_servers: str,
            group_id: str,
            **consumer_kwargs: Any,
    ) -> AsyncGenerator[KafkaConsumerWithCircuitBreaker, None]:
        """Create Kafka consumer with circuit breaker.
        
        Args:
            *topics: Topics to consume from
            bootstrap_servers: Kafka bootstrap servers
            group_id: Consumer group ID
            **consumer_kwargs: Additional consumer configuration
            
        Yields:
            KafkaConsumerWithCircuitBreaker instance
        """
        consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            **consumer_kwargs,
        )

        await consumer.start()
        wrapped_consumer = KafkaConsumerWithCircuitBreaker(
            consumer, self._manager
        )

        try:
            yield wrapped_consumer
        finally:
            await wrapped_consumer.close()
