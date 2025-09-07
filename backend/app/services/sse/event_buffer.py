import asyncio
import gc
import sys
import time
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

from app.core.logging import logger
from app.core.metrics.context import get_event_metrics
from app.core.utils import StringEnum

T = TypeVar('T')


class BufferPriority(StringEnum):
    """Priority levels for buffered events."""
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class BufferedItem(Generic[T]):
    """Container for buffered items with metadata."""

    __slots__ = ('item', 'timestamp', 'priority', 'size_bytes', 'retry_count', 'source')

    def __init__(
            self,
            item: T,
            priority: BufferPriority = BufferPriority.NORMAL,
            source: str = "unknown"
    ):
        self.item = item
        self.timestamp = time.time()
        self.priority = priority
        self.retry_count = 0
        self.source = source
        self.size_bytes = self._calculate_size()

    def _calculate_size(self) -> int:
        """Calculate actual size of the item in bytes."""
        try:
            # For strings
            if isinstance(self.item, str):
                return len(self.item.encode('utf-8'))
            # For bytes
            elif isinstance(self.item, bytes):
                return len(self.item)
            # For dicts (common for events)
            elif isinstance(self.item, dict):
                return sys.getsizeof(self.item) + sum(
                    sys.getsizeof(k) + sys.getsizeof(v)
                    for k, v in self.item.items()
                )
            # For objects with __dict__ (account for attribute dict storage)
            elif hasattr(self.item, '__dict__'):
                return sys.getsizeof(self.item) + sys.getsizeof(self.item.__dict__)
            else:
                # Fallback to interpreter-reported size
                return sys.getsizeof(self.item)
        except Exception:
            # Conservative estimate if calculation fails
            return 1024

    @property
    def age_seconds(self) -> float:
        """Age of the item in seconds."""
        return time.time() - self.timestamp


class EventBuffer(Generic[T]):
    """
    Comprehensive event buffer with full metrics tracking, backpressure management,
    and memory monitoring.
    """

    def __init__(
            self,
            maxsize: int = 1000,
            buffer_name: str = "default",
            max_memory_mb: float = 100.0,
            enable_priority: bool = True,
            backpressure_high_watermark: float = 0.8,
            backpressure_low_watermark: float = 0.6,
            ttl_seconds: float | None = 300.0  # 5 minutes default TTL
    ):
        """
        Initialize event buffer with comprehensive configuration.
        
        Args:
            maxsize: Maximum number of items in buffer
            buffer_name: Name for metrics identification
            max_memory_mb: Maximum memory usage in MB
            enable_priority: Enable priority-based processing
            backpressure_high_watermark: Threshold to activate backpressure (0.0-1.0)
            backpressure_low_watermark: Threshold to deactivate backpressure (0.0-1.0)
            ttl_seconds: Time-to-live for items in buffer (None = no expiry)
        """
        # Priority queues if enabled, otherwise single queue
        self._queues: dict[BufferPriority, asyncio.Queue[BufferedItem[T]]] | None = None
        if enable_priority:
            self._queues = {
                BufferPriority.CRITICAL: asyncio.Queue(maxsize=maxsize // 4),
                BufferPriority.HIGH: asyncio.Queue(maxsize=maxsize // 4),
                BufferPriority.NORMAL: asyncio.Queue(maxsize=maxsize // 2),
                BufferPriority.LOW: asyncio.Queue(maxsize=maxsize // 4)
            }
        else:
            self._queue: asyncio.Queue[BufferedItem[T]] = asyncio.Queue(maxsize=maxsize)

        # TODO: EventMetrics is now a singleton to prevent metric inconsistencies
        # Previously, each EventBuffer created its own EventMetrics instance,
        # causing the event_buffer_size metric to show incorrect cumulative values
        # (alternating 0-2 pattern). Now all buffers share the same metrics instance.
        self._metrics = get_event_metrics()  # Singleton via __new__, same as EventMetrics.get_instance()
        self._buffer_name = buffer_name
        self._maxsize = maxsize
        self._max_memory_mb = max_memory_mb
        self._enable_priority = enable_priority
        self._ttl_seconds = ttl_seconds

        # Backpressure thresholds
        self._backpressure_high = int(maxsize * backpressure_high_watermark)
        self._backpressure_low = int(maxsize * backpressure_low_watermark)
        self._backpressure_active = False

        # Statistics
        self._total_processed = 0
        self._total_dropped = 0
        self._total_expired = 0
        self._total_bytes_processed = 0
        self._current_memory_bytes = 0
        self._peak_memory_bytes = 0
        self._last_gc_time = time.time()

        # Locks for thread safety
        self._stats_lock = asyncio.Lock()
        self._memory_lock = asyncio.Lock()

        # Start background tasks
        self._running = True
        self._ttl_task: asyncio.Task | None = None
        self._metrics_task: asyncio.Task | None = None
        if self._ttl_seconds:
            self._ttl_task = asyncio.create_task(self._ttl_monitor())
        self._metrics_task = asyncio.create_task(self._metrics_reporter())

    @property
    def size(self) -> int:
        """Current total number of items across all queues."""
        if self._enable_priority and self._queues:
            return sum(q.qsize() for q in self._queues.values())
        else:
            return self._queue.qsize()

    @property
    def is_full(self) -> bool:
        """Check if buffer has reached max capacity."""
        return self.size >= self._maxsize

    @property
    def is_empty(self) -> bool:
        """Check if buffer is completely empty."""
        if self._enable_priority and self._queues:
            return all(q.empty() for q in self._queues.values())
        else:
            return self._queue.empty()

    @property
    def memory_usage_mb(self) -> float:
        """Current memory usage in MB."""
        return self._current_memory_bytes / (1024 * 1024)

    async def put(
            self,
            item: T,
            priority: BufferPriority = BufferPriority.NORMAL,
            timeout: float | None = None,
            source: str = "unknown"
    ) -> bool:
        """
        Add an item to the buffer with full metrics tracking.
        
        Args:
            item: The item to buffer
            priority: Priority level for the item
            timeout: Maximum time to wait for space
            source: Source identifier for metrics
        
        Returns:
            True if item was added, False if dropped
        """
        buffered_item = BufferedItem(item, priority=priority, source=source)

        # Check memory limit
        async with self._memory_lock:
            new_memory = self._current_memory_bytes + buffered_item.size_bytes
            if new_memory > self._max_memory_mb * 1024 * 1024:
                await self._drop_item(buffered_item, reason="memory_limit")
                return False
            self._current_memory_bytes = new_memory
            self._peak_memory_bytes = max(self._peak_memory_bytes, new_memory)

        # Update metrics for buffer size increase
        self._metrics.update_event_buffer_size(1)

        # Check and activate backpressure if needed
        await self._check_backpressure()

        # Select appropriate queue
        if self._enable_priority and self._queues:
            queue = self._queues[priority]
        else:
            queue = self._queue

        try:
            if timeout:
                await asyncio.wait_for(queue.put(buffered_item), timeout=timeout)
            else:
                await queue.put(buffered_item)

            logger.debug(
                f"Item added to buffer '{self._buffer_name}' "
                f"(priority: {priority}, size: {buffered_item.size_bytes} bytes, "
                f"total: {self.size}/{self._maxsize})"
            )
            return True

        except asyncio.TimeoutError:
            await self._drop_item(buffered_item, reason="timeout")
            return False
        except asyncio.QueueFull:
            await self._drop_item(buffered_item, reason="queue_full")
            return False
        except Exception as e:
            logger.error(f"Error adding item to buffer: {e}")
            await self._drop_item(buffered_item, reason="error")
            return False

    async def get(
            self,
            timeout: float | None = None,
            priority_order: list[BufferPriority] | None = None
    ) -> T | None:
        """
        Get an item from the buffer with full metrics tracking.
        
        Args:
            timeout: Maximum time to wait for an item
            priority_order: Custom priority order (if priority enabled)
        
        Returns:
            The item, or None if timeout/empty
        """
        if self._enable_priority and self._queues:
            # Check queues in priority order
            if priority_order is None:
                priority_order = [
                    BufferPriority.CRITICAL,
                    BufferPriority.HIGH,
                    BufferPriority.NORMAL,
                    BufferPriority.LOW
                ]

            for priority in priority_order:
                queue = self._queues[priority]
                if not queue.empty():
                    try:
                        buffered_item = queue.get_nowait()
                        return await self._process_item(buffered_item)
                    except asyncio.QueueEmpty:
                        continue

            # If all priority queues are empty, wait on highest priority
            queue = self._queues[priority_order[0]]
        else:
            queue = self._queue

        # Wait for item with timeout
        try:
            if timeout:
                buffered_item = await asyncio.wait_for(queue.get(), timeout=timeout)
            else:
                buffered_item = await queue.get()

            return await self._process_item(buffered_item)

        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.error(f"Error getting item from buffer: {e}")
            return None

    async def _process_item(self, buffered_item: BufferedItem[T]) -> T:
        """Process an item retrieved from the buffer."""
        # Calculate and record latency
        latency = buffered_item.age_seconds

        # Update memory tracking
        async with self._memory_lock:
            self._current_memory_bytes -= buffered_item.size_bytes
            self._total_bytes_processed += buffered_item.size_bytes

        # Update metrics
        async with self._stats_lock:
            self._total_processed += 1

        self._metrics.record_event_buffer_latency(latency)
        self._metrics.record_event_buffer_processed()
        self._metrics.update_event_buffer_size(-1)

        # Check and release backpressure if needed
        await self._check_backpressure()

        logger.debug(
            f"Item processed from buffer '{self._buffer_name}' "
            f"(latency: {latency:.3f}s, size: {buffered_item.size_bytes} bytes)"
        )

        return buffered_item.item

    async def get_batch(
            self,
            max_items: int = 10,
            timeout: float = 0.1,
            max_bytes: int | None = None
    ) -> list[T]:
        """
        Get multiple items from the buffer efficiently.
        
        Args:
            max_items: Maximum number of items to retrieve
            timeout: Maximum time to wait
            max_bytes: Maximum total bytes to retrieve
        
        Returns:
            List of items retrieved
        """
        items: list[T] = []
        total_bytes = 0
        end_time = time.time() + timeout

        while len(items) < max_items and time.time() < end_time:
            remaining_timeout = max(0.001, end_time - time.time())

            item = await self.get(timeout=remaining_timeout)
            if item is not None:
                items.append(item)

                # Check byte limit if specified
                if max_bytes and hasattr(item, '__sizeof__'):
                    total_bytes += sys.getsizeof(item)
                    if total_bytes >= max_bytes:
                        break
            else:
                # No more items available within timeout
                break

        return items

    async def stream(self, batch_size: int = 1) -> AsyncGenerator[T | list[T], None]:
        """
        Stream items from the buffer as they become available.
        
        Args:
            batch_size: Number of items to yield at once (1 = single items)
        
        Yields:
            Items from the buffer (single or batched)
        """
        while self._running:
            if batch_size == 1:
                item = await self.get(timeout=1.0)
                if item is not None:
                    yield item
            else:
                items = await self.get_batch(max_items=batch_size, timeout=1.0)
                if items:
                    yield items

    async def _drop_item(
            self,
            buffered_item: BufferedItem[T],
            reason: str = "unknown"
    ) -> None:
        """Record metrics for a dropped item."""
        async with self._stats_lock:
            self._total_dropped += 1

        self._metrics.record_event_buffer_dropped()

        logger.warning(
            f"Item dropped from buffer '{self._buffer_name}' "
            f"(reason: {reason}, priority: {buffered_item.priority}, "
            f"source: {buffered_item.source})"
        )

    async def _check_backpressure(self) -> None:
        """Check and update backpressure state."""
        current_size = self.size

        if not self._backpressure_active and current_size >= self._backpressure_high:
            self._backpressure_active = True
            self._metrics.set_event_buffer_backpressure(True)
            logger.warning(
                f"Backpressure ACTIVATED for buffer '{self._buffer_name}' "
                f"(size: {current_size}/{self._maxsize}, "
                f"memory: {self.memory_usage_mb:.2f}MB)"
            )
        elif self._backpressure_active and current_size <= self._backpressure_low:
            self._backpressure_active = False
            self._metrics.set_event_buffer_backpressure(False)
            logger.info(
                f"Backpressure RELEASED for buffer '{self._buffer_name}' "
                f"(size: {current_size}/{self._maxsize}, "
                f"memory: {self.memory_usage_mb:.2f}MB)"
            )

    async def _ttl_monitor(self) -> None:
        """Background task to expire old items based on TTL."""
        while self._running:
            try:
                await asyncio.sleep(10)  # Check every 10 seconds

                if not self._ttl_seconds:
                    continue

                expired_count = 0

                if self._enable_priority and self._queues:
                    for queue in self._queues.values():
                        expired_count += await self._expire_from_queue(queue)
                else:
                    expired_count += await self._expire_from_queue(self._queue)

                if expired_count > 0:
                    logger.info(
                        f"Expired {expired_count} items from buffer '{self._buffer_name}'"
                    )
                    async with self._stats_lock:
                        self._total_expired += expired_count

            except Exception as e:
                logger.error(f"Error in TTL monitor: {e}")

    async def _expire_from_queue(self, queue: asyncio.Queue) -> int:
        """Expire old items from a specific queue."""
        if not self._ttl_seconds:
            return 0

        expired_count = 0
        temp_items = []

        # Get all items to check age
        while not queue.empty():
            try:
                item = queue.get_nowait()
                if item.age_seconds > self._ttl_seconds:
                    expired_count += 1
                    async with self._memory_lock:
                        self._current_memory_bytes -= item.size_bytes
                    self._metrics.update_event_buffer_size(-1)
                else:
                    temp_items.append(item)
            except asyncio.QueueEmpty:
                break

        # Put back non-expired items
        for item in temp_items:
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                # Queue filled up while we were checking - shouldn't happen
                logger.error("Failed to restore item to queue after TTL check")

        return expired_count

    async def _metrics_reporter(self) -> None:
        """Background task to report metrics periodically."""
        # Report initial metrics immediately on startup
        self._metrics.record_event_buffer_memory_usage(self.memory_usage_mb)

        while self._running:
            await asyncio.sleep(5)  # Report every 5 seconds for better visibility

            # Report memory usage
            self._metrics.record_event_buffer_memory_usage(
                self.memory_usage_mb
            )

            # Trigger garbage collection if memory is high
            if self.memory_usage_mb > self._max_memory_mb * 0.9:
                gc.collect()
                self._last_gc_time = time.time()

            # Log statistics periodically (every 30 seconds)
            if int(time.time()) % 30 == 0:
                stats = await self.get_stats()
                logger.info(
                    f"Buffer '{self._buffer_name}' stats: "
                    f"size={stats['size']}/{stats['maxsize']}, "
                    f"processed={stats['total_processed']}, "
                    f"dropped={stats['total_dropped']}, "
                    f"memory={stats['memory_usage_mb']:.2f}MB"
                )

    async def get_stats(self) -> dict[str, Any]:
        """
        Get comprehensive buffer statistics.
        """
        async with self._stats_lock:
            total_items = self._total_processed + self._total_dropped

            # Get queue-specific stats if priority enabled
            queue_stats = {}
            if self._enable_priority and self._queues:
                for priority, queue in self._queues.items():
                    queue_stats[priority.value] = {
                        "size": queue.qsize(),
                        "maxsize": queue.maxsize,
                        "utilization": queue.qsize() / max(1, queue.maxsize)
                    }

            return {
                "name": self._buffer_name,
                "size": self.size,
                "maxsize": self._maxsize,
                "utilization": self.size / max(1, self._maxsize),
                "backpressure_active": self._backpressure_active,
                "total_processed": self._total_processed,
                "total_dropped": self._total_dropped,
                "total_expired": self._total_expired,
                "drop_rate": self._total_dropped / max(1, total_items),
                "memory_usage_mb": self.memory_usage_mb,
                "memory_limit_mb": self._max_memory_mb,
                "memory_utilization": self.memory_usage_mb / max(1, self._max_memory_mb),
                "peak_memory_mb": self._peak_memory_bytes / (1024 * 1024),
                "total_bytes_processed": self._total_bytes_processed,
                "avg_item_size_bytes": self._total_bytes_processed / max(1, self._total_processed),
                "ttl_seconds": self._ttl_seconds,
                "priority_enabled": self._enable_priority,
                "queue_stats": queue_stats,
                "last_gc_time": datetime.fromtimestamp(self._last_gc_time, tz=timezone.utc).isoformat()
            }

    async def shutdown(self) -> None:
        """Gracefully shutdown the buffer and its background tasks."""
        logger.info(f"Shutting down buffer '{self._buffer_name}'")
        self._running = False

        # Cancel background tasks
        if self._ttl_task:
            self._ttl_task.cancel()
            try:
                await self._ttl_task
            except asyncio.CancelledError:
                pass

        if self._metrics_task:
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass

        # Report final stats
        stats = await self.get_stats()
        logger.info(f"Final buffer stats: {stats}")
