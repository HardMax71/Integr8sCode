"""Event buffer with backpressure handling for high-throughput event processing"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Deque, Dict, List, Optional
from uuid import uuid4

from app.config import Settings, get_settings
from app.core.logging import logger
from app.core.metrics import (
    EVENT_BUFFER_DROPPED,
    EVENT_BUFFER_LATENCY,
    EVENT_BUFFER_PROCESSED,
    EVENT_BUFFER_SIZE,
)


class BackpressureStrategy(Enum):
    """Strategies for handling backpressure"""
    DROP_OLDEST = "drop_oldest"
    DROP_NEWEST = "drop_newest"
    BLOCK = "block"
    SAMPLE = "sample"
    PRIORITY = "priority"


class EventPriority(Enum):
    """Event priority levels"""
    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4


@dataclass
class BufferedEvent:
    """Event with metadata for buffering"""
    event_id: str
    event_type: str
    payload: Dict[str, Any]
    timestamp: datetime
    priority: EventPriority = EventPriority.NORMAL
    retry_count: int = 0
    correlation_id: Optional[str] = None
    source: Optional[str] = None
    ttl: Optional[timedelta] = None
    size_bytes: int = 0


@dataclass
class BufferStats:
    """Statistics for event buffer"""
    total_events: int = 0
    processed_events: int = 0
    dropped_events: int = 0
    current_size: int = 0
    max_size_reached: int = 0
    total_latency: float = 0.0
    backpressure_activations: int = 0
    strategy_counts: Dict[str, int] = field(default_factory=dict)


class EventBuffer:
    """
    Event buffer with sophisticated backpressure handling.
    
    Features:
    - Multiple backpressure strategies
    - Priority-based processing
    - TTL support for events
    - Batch processing
    - Flow control
    - Memory management
    - Statistics and monitoring
    """

    def __init__(
        self,
        max_size: int = 10000,
        batch_size: int = 100,
        batch_timeout: float = 1.0,
        max_memory_mb: int = 100,
        backpressure_strategy: BackpressureStrategy = BackpressureStrategy.DROP_OLDEST,
        backpressure_threshold: float = 0.8,
        settings: Optional[Settings] = None
    ):
        self.settings = settings or get_settings()
        self.max_size = max_size
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.backpressure_strategy = backpressure_strategy
        self.backpressure_threshold = backpressure_threshold

        # Buffers by priority
        self._buffers: Dict[EventPriority, Deque[BufferedEvent]] = {
            priority: deque() for priority in EventPriority
        }

        # Processing state
        self._processor: Optional[Callable] = None
        self._processing_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._backpressure_active = False
        self._last_backpressure_time = 0.0
        self._current_memory_usage = 0

        # Flow control
        self._input_semaphore = asyncio.Semaphore(max_size)
        self._processing_lock = asyncio.Lock()
        self._drain_event = asyncio.Event()
        self._drain_event.set()  # Start in drained state

        # Statistics
        self._stats = BufferStats()
        self._event_handlers: Dict[str, List[Callable]] = {}

        # Sampling state for sample strategy
        self._sample_counter = 0
        self._sample_rate = 0.1  # Keep 10% of events during backpressure

        # Event type priorities for priority strategy
        self._event_type_priorities: Dict[str, EventPriority] = {}

        logger.info(
            f"EventBuffer initialized: max_size={max_size}, "
            f"batch_size={batch_size}, strategy={backpressure_strategy.value}"
        )

    async def start(self, processor: Callable[[List[BufferedEvent]], None]) -> None:
        """Start the event buffer with a processor function"""
        if self._processing_task:
            logger.warning("EventBuffer already started")
            return

        self._processor = processor
        self._shutdown_event.clear()
        self._processing_task = asyncio.create_task(self._process_loop())
        logger.info("EventBuffer started")

    async def stop(self, timeout: float = 30.0) -> None:
        """Stop the event buffer gracefully"""
        logger.info("Stopping EventBuffer...")
        self._shutdown_event.set()

        if self._processing_task:
            try:
                await asyncio.wait_for(self._processing_task, timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(f"EventBuffer shutdown timed out after {timeout}s")
                self._processing_task.cancel()
                try:
                    await self._processing_task
                except asyncio.CancelledError:
                    pass

        # Process remaining events
        remaining = await self._drain_all_buffers()
        if remaining > 0:
            logger.warning(f"EventBuffer stopped with {remaining} unprocessed events")

        logger.info("EventBuffer stopped")

    async def add_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        priority: EventPriority = EventPriority.NORMAL,
        correlation_id: Optional[str] = None,
        source: Optional[str] = None,
        ttl: Optional[timedelta] = None
    ) -> bool:
        """
        Add an event to the buffer.
        
        Returns:
            True if event was added, False if dropped due to backpressure
        """
        event = BufferedEvent(
            event_id=str(uuid4()),
            event_type=event_type,
            payload=payload,
            timestamp=datetime.now(timezone.utc),
            priority=priority,
            correlation_id=correlation_id,
            source=source,
            ttl=ttl,
            size_bytes=self._estimate_event_size(payload)
        )

        # Check memory limit
        if self._current_memory_usage + event.size_bytes > self.max_memory_bytes:
            logger.warning(f"Memory limit exceeded, dropping event {event.event_id}")
            self._stats.dropped_events += 1
            EVENT_BUFFER_DROPPED.labels(
                event_type=event_type,
                reason="memory_limit"
            ).inc()
            return False

        # Check if backpressure should be activated
        current_size = self.get_current_size()
        if current_size >= self.max_size * self.backpressure_threshold:
            return await self._handle_backpressure(event)

        # Normal operation - add to buffer
        try:
            # Use semaphore for blocking strategy
            if self.backpressure_strategy == BackpressureStrategy.BLOCK:
                await asyncio.wait_for(
                    self._input_semaphore.acquire(),
                    timeout=5.0
                )

            self._buffers[priority].append(event)
            self._current_memory_usage += event.size_bytes
            self._stats.total_events += 1
            self._drain_event.clear()  # Signal that buffer is not empty

            # Update metrics
            EVENT_BUFFER_SIZE.labels(priority=priority.name).set(
                len(self._buffers[priority])
            )

            return True

        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for buffer space, dropping event {event.event_id}")
            self._stats.dropped_events += 1
            EVENT_BUFFER_DROPPED.labels(
                event_type=event_type,
                reason="timeout"
            ).inc()
            return False

    async def _handle_backpressure(self, event: BufferedEvent) -> bool:
        """Handle backpressure based on configured strategy"""
        if not self._backpressure_active:
            self._backpressure_active = True
            self._last_backpressure_time = time.time()
            self._stats.backpressure_activations += 1
            logger.warning(
                f"Backpressure activated: strategy={self.backpressure_strategy.value}, "
                f"buffer_size={self.get_current_size()}"
            )

        strategy = self.backpressure_strategy
        self._stats.strategy_counts[strategy.value] = self._stats.strategy_counts.get(strategy.value, 0) + 1

        if strategy == BackpressureStrategy.DROP_OLDEST:
            # Remove oldest event from same or lower priority
            for priority in sorted(EventPriority, key=lambda p: p.value, reverse=True):
                if priority.value >= event.priority.value and self._buffers[priority]:
                    dropped = self._buffers[priority].popleft()
                    self._current_memory_usage -= dropped.size_bytes
                    self._stats.dropped_events += 1
                    EVENT_BUFFER_DROPPED.labels(
                        event_type=dropped.event_type,
                        reason="backpressure_drop_oldest"
                    ).inc()

                    # Add new event
                    self._buffers[event.priority].append(event)
                    self._current_memory_usage += event.size_bytes
                    self._stats.total_events += 1
                    return True

            # No space found
            self._stats.dropped_events += 1
            EVENT_BUFFER_DROPPED.labels(
                event_type=event.event_type,
                reason="backpressure_no_space"
            ).inc()
            return False

        elif strategy == BackpressureStrategy.DROP_NEWEST:
            # Simply drop the new event
            self._stats.dropped_events += 1
            EVENT_BUFFER_DROPPED.labels(
                event_type=event.event_type,
                reason="backpressure_drop_newest"
            ).inc()
            return False

        elif strategy == BackpressureStrategy.SAMPLE:
            # Keep only a sample of events
            self._sample_counter += 1
            if self._sample_counter % int(1 / self._sample_rate) == 0:
                # This event is selected
                # Make room by dropping oldest
                for priority in sorted(EventPriority, key=lambda p: p.value, reverse=True):
                    if self._buffers[priority]:
                        dropped = self._buffers[priority].popleft()
                        self._current_memory_usage -= dropped.size_bytes
                        self._stats.dropped_events += 1

                        self._buffers[event.priority].append(event)
                        self._current_memory_usage += event.size_bytes
                        self._stats.total_events += 1
                        return True

            self._stats.dropped_events += 1
            EVENT_BUFFER_DROPPED.labels(
                event_type=event.event_type,
                reason="backpressure_sampling"
            ).inc()
            return False

        elif strategy == BackpressureStrategy.PRIORITY:
            # Drop lower priority events
            for priority in sorted(EventPriority, key=lambda p: p.value, reverse=True):
                if priority.value > event.priority.value and self._buffers[priority]:
                    dropped = self._buffers[priority].popleft()
                    self._current_memory_usage -= dropped.size_bytes
                    self._stats.dropped_events += 1
                    EVENT_BUFFER_DROPPED.labels(
                        event_type=dropped.event_type,
                        reason="backpressure_priority"
                    ).inc()

                    self._buffers[event.priority].append(event)
                    self._current_memory_usage += event.size_bytes
                    self._stats.total_events += 1
                    return True

            # No lower priority events to drop
            self._stats.dropped_events += 1
            EVENT_BUFFER_DROPPED.labels(
                event_type=event.event_type,
                reason="backpressure_priority_full"
            ).inc()
            return False

        return False

    async def _process_loop(self) -> None:
        """Main processing loop"""
        logger.info("EventBuffer processing loop started")

        while not self._shutdown_event.is_set():
            try:
                # Collect batch
                batch = await self._collect_batch()

                if batch:
                    # Process batch
                    start_time = time.time()

                    async with self._processing_lock:
                        if self._processor:
                            try:
                                if asyncio.iscoroutinefunction(self._processor):
                                    await self._processor(batch)
                                else:
                                    await asyncio.to_thread(self._processor, batch)

                                # Update statistics
                                processing_time = time.time() - start_time
                                self._stats.processed_events += len(batch)
                                self._stats.total_latency += processing_time

                                # Update metrics
                                for event in batch:
                                    EVENT_BUFFER_PROCESSED.labels(
                                        event_type=event.event_type
                                    ).inc()

                                    latency = (datetime.now(timezone.utc) - event.timestamp).total_seconds()
                                    EVENT_BUFFER_LATENCY.labels(
                                        event_type=event.event_type
                                    ).observe(latency)

                                # Release semaphores if using blocking strategy
                                if self.backpressure_strategy == BackpressureStrategy.BLOCK:
                                    for _ in range(len(batch)):
                                        self._input_semaphore.release()

                            except Exception as e:
                                logger.error(f"Error processing batch: {e}")
                                # Return events to buffer on error
                                await self._return_to_buffer(batch)

                    # Check if backpressure can be deactivated
                    if self._backpressure_active and self.get_current_size() < self.max_size * 0.6:
                        self._backpressure_active = False
                        duration = time.time() - self._last_backpressure_time
                        logger.info(f"Backpressure deactivated after {duration:.2f}s")

                else:
                    # No events to process
                    self._drain_event.set()
                    await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                logger.info("EventBuffer processing loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in processing loop: {e}")
                await asyncio.sleep(1.0)

        logger.info("EventBuffer processing loop stopped")

    async def _collect_batch(self) -> List[BufferedEvent]:
        """Collect a batch of events for processing"""
        batch: List[BufferedEvent] = []
        batch_start_time = time.time()

        # Collect events by priority
        for priority in sorted(EventPriority, key=lambda p: p.value):
            buffer = self._buffers[priority]

            while buffer and len(batch) < self.batch_size:
                # Check timeout
                if time.time() - batch_start_time > self.batch_timeout:
                    break

                event = buffer[0]  # Peek at first event

                # Check TTL
                if event.ttl and datetime.now(timezone.utc) - event.timestamp > event.ttl:
                    # Event expired
                    expired = buffer.popleft()
                    self._current_memory_usage -= expired.size_bytes
                    self._stats.dropped_events += 1
                    EVENT_BUFFER_DROPPED.labels(
                        event_type=expired.event_type,
                        reason="ttl_expired"
                    ).inc()
                    continue

                # Add to batch
                batch.append(buffer.popleft())
                self._current_memory_usage -= event.size_bytes

            if len(batch) >= self.batch_size:
                break

        # Update buffer size metrics
        for priority in EventPriority:
            EVENT_BUFFER_SIZE.labels(priority=priority.name).set(
                len(self._buffers[priority])
            )

        return batch

    async def _return_to_buffer(self, events: List[BufferedEvent]) -> None:
        """Return events to buffer after processing failure"""
        for event in reversed(events):  # Maintain order
            event.retry_count += 1
            if event.retry_count > 3:
                logger.warning(f"Event {event.event_id} exceeded retry limit, dropping")
                self._stats.dropped_events += 1
                EVENT_BUFFER_DROPPED.labels(
                    event_type=event.event_type,
                    reason="retry_limit"
                ).inc()
            else:
                self._buffers[event.priority].appendleft(event)
                self._current_memory_usage += event.size_bytes

    async def _drain_all_buffers(self) -> int:
        """Drain all buffers and return count of remaining events"""
        total = 0
        for buffer in self._buffers.values():
            total += len(buffer)
            buffer.clear()

        self._current_memory_usage = 0
        self._drain_event.set()
        return total

    def _estimate_event_size(self, payload: Dict[str, Any]) -> int:
        """Estimate memory size of event payload"""
        # Simple estimation - can be made more sophisticated
        import sys
        return sys.getsizeof(str(payload))

    def get_current_size(self) -> int:
        """Get total number of events in all buffers"""
        return sum(len(buffer) for buffer in self._buffers.values())

    def get_statistics(self) -> BufferStats:
        """Get buffer statistics"""
        self._stats.current_size = self.get_current_size()
        self._stats.max_size_reached = max(
            self._stats.max_size_reached,
            self._stats.current_size
        )
        return self._stats

    def set_event_priority(self, event_type: str, priority: EventPriority) -> None:
        """Set priority for a specific event type"""
        self._event_type_priorities[event_type] = priority

    async def wait_for_drain(self, timeout: Optional[float] = None) -> bool:
        """Wait for buffer to be drained"""
        try:
            await asyncio.wait_for(self._drain_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def is_backpressure_active(self) -> bool:
        """Check if backpressure is currently active"""
        return self._backpressure_active

    def get_memory_usage_mb(self) -> float:
        """Get current memory usage in MB"""
        return self._current_memory_usage / (1024 * 1024)


class EventBufferManager:
    """Manages multiple event buffers for different purposes"""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._buffers: Dict[str, EventBuffer] = {}
        self._lock = asyncio.Lock()

    async def create_buffer(
        self,
        name: str,
        max_size: int = 10000,
        batch_size: int = 100,
        batch_timeout: float = 1.0,
        backpressure_strategy: BackpressureStrategy = BackpressureStrategy.DROP_OLDEST,
        processor: Optional[Callable] = None
    ) -> EventBuffer:
        """Create a new named buffer"""
        async with self._lock:
            if name in self._buffers:
                raise ValueError(f"Buffer '{name}' already exists")

            buffer = EventBuffer(
                max_size=max_size,
                batch_size=batch_size,
                batch_timeout=batch_timeout,
                backpressure_strategy=backpressure_strategy,
                settings=self.settings
            )

            if processor:
                await buffer.start(processor)

            self._buffers[name] = buffer
            logger.info(f"Created event buffer '{name}'")

            return buffer

    async def get_buffer(self, name: str) -> Optional[EventBuffer]:
        """Get a buffer by name"""
        return self._buffers.get(name)

    async def remove_buffer(self, name: str) -> None:
        """Remove and stop a buffer"""
        async with self._lock:
            if name in self._buffers:
                buffer = self._buffers[name]
                await buffer.stop()
                del self._buffers[name]
                logger.info(f"Removed event buffer '{name}'")

    async def stop_all(self) -> None:
        """Stop all buffers"""
        async with self._lock:
            tasks = []
            for buffer in self._buffers.values():
                tasks.append(buffer.stop())

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            self._buffers.clear()
            logger.info("All event buffers stopped")

    def get_all_statistics(self) -> Dict[str, BufferStats]:
        """Get statistics for all buffers"""
        return {
            name: buffer.get_statistics()
            for name, buffer in self._buffers.items()
        }
