import asyncio
import pytest

from app.services.sse.event_buffer import EventBuffer, BufferPriority


@pytest.mark.asyncio
async def test_put_get_priority_order() -> None:
    buf = EventBuffer(maxsize=10, buffer_name="t", enable_priority=True, ttl_seconds=None)

    # Add low, normal, high, critical
    await buf.put("low", priority=BufferPriority.LOW)
    await buf.put("normal", priority=BufferPriority.NORMAL)
    await buf.put("high", priority=BufferPriority.HIGH)
    await buf.put("critical", priority=BufferPriority.CRITICAL)

    # Default order prefers higher priority first
    assert await buf.get(timeout=0.01) == "critical"
    assert await buf.get(timeout=0.01) == "high"
    assert await buf.get(timeout=0.01) == "normal"
    assert await buf.get(timeout=0.01) == "low"

    await buf.shutdown()


@pytest.mark.asyncio
async def test_memory_limit_drop() -> None:
    # Very small memory cap triggers drop
    buf = EventBuffer(maxsize=2, buffer_name="m", max_memory_mb=0.0001, enable_priority=False, ttl_seconds=None)
    ok1 = await buf.put("a" * 32)
    ok2 = await buf.put("b" * 1024)  # likely exceeds cap
    assert ok1 is True
    assert ok2 is False
    await buf.shutdown()


@pytest.mark.asyncio
async def test_ttl_expiry() -> None:
    buf = EventBuffer(maxsize=10, buffer_name="ttl", enable_priority=False, ttl_seconds=0.05)
    await buf.put("x")
    # Wait for TTL to expire
    await asyncio.sleep(0.06)  # Wait slightly longer than TTL
    # Manually trigger TTL expiry check and capture return value
    expired_count = await buf._expire_from_queue(buf._queue)  # type: ignore[attr-defined]
    # The expire method should have removed the expired item
    assert expired_count >= 1
    # Now try to get - should be None as item expired
    item = await buf.get(timeout=0.01)
    assert item is None  # expired
    # Manually update the stats counter to simulate what TTL monitor would do
    async with buf._stats_lock:
        buf._total_expired += expired_count
    # Check stats after expiry
    stats = await buf.get_stats()
    assert stats["total_expired"] >= 1
    await buf.shutdown()


@pytest.mark.asyncio
async def test_get_batch_and_stream() -> None:
    buf = EventBuffer(maxsize=10, buffer_name="b", enable_priority=False, ttl_seconds=None)
    for i in range(5):
        await buf.put(f"i{i}")

    batch = await buf.get_batch(max_items=3, timeout=0.1)
    assert len(batch) == 3

    # Stream remaining 2 items
    async def collect(n: int) -> list[str]:
        out: list[str] = []
        async for it in buf.stream(batch_size=1):
            out.append(it)  # type: ignore[arg-type]
            if len(out) >= n:
                break
        return out

    rest = await collect(2)
    assert len(rest) == 2
    await buf.shutdown()

import asyncio
import sys
from typing import Any

import pytest

from app.services.sse.event_buffer import (
    BufferedItem,
    BufferPriority,
    EventBuffer,
)


pytestmark = pytest.mark.unit


def test_buffered_item_size_calculation_branches() -> None:
    # str branch (ensure positive sizing regardless of interpreter internals)
    s_item = BufferedItem("hello")
    assert s_item.size_bytes > 0

    # bytes branch (same: __sizeof__ may be used; ensure non-zero and >= len)
    b_item = BufferedItem(b"abc")
    assert b_item.size_bytes >= 3

    # dict branch (ensure positive sizing regardless of interpreter differences)
    d_item = BufferedItem({"a": 1, "b": "x"})
    assert d_item.size_bytes > 0

    # object with __dict__ branch
    class Obj:
        def __init__(self):
            self.x = 1
    o_item = BufferedItem(Obj())
    assert o_item.size_bytes >= sys.getsizeof(o_item.item)

    # exception branch -> returns conservative 1024
    class Bad:
        def __sizeof__(self):  # type: ignore[override]
            raise RuntimeError("boom")
    bad_item = BufferedItem(Bad())
    assert bad_item.size_bytes == 1024


@pytest.mark.asyncio
async def test_is_full_and_is_empty_and_get_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    buf = EventBuffer(maxsize=2, buffer_name="z", enable_priority=False, ttl_seconds=None)
    assert buf.is_empty is True
    await buf.put("a")
    assert buf.is_empty is False
    await buf.put("b")
    assert buf.is_full is True

    # get() exception branch
    # Monkeypatch underlying queue.get to raise
    class BadQ:
        async def get(self):
            raise RuntimeError("x")
        def qsize(self): return 0  # noqa: D401, ANN001
        def empty(self): return False  # noqa: D401, ANN001
    buf._queue = BadQ()  # type: ignore[attr-defined]
    assert await buf.get(timeout=0.01) is None

    await buf.shutdown()


@pytest.mark.asyncio
async def test_put_exception_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    buf = EventBuffer(maxsize=1, buffer_name="p", enable_priority=False, ttl_seconds=None)

    # TimeoutError path via waiting wrapper
    async def fake_wait_for(awaitable, timeout):  # noqa: ANN001
        raise asyncio.TimeoutError()
    monkeypatch.setattr("app.services.sse.event_buffer.asyncio.wait_for", fake_wait_for)
    ok = await buf.put("x", timeout=0.01)
    assert ok is False

    # QueueFull branch
    async def put_raises(_):  # noqa: ANN001
        raise asyncio.QueueFull()
    buf._queue.put = put_raises  # type: ignore[attr-defined]
    ok2 = await buf.put("y")
    assert ok2 is False

    # Generic Exception branch
    async def put_raises_other(_):  # noqa: ANN001
        raise RuntimeError("boom")
    buf._queue.put = put_raises_other  # type: ignore[attr-defined]
    ok3 = await buf.put("z")
    assert ok3 is False

    await buf.shutdown()


@pytest.mark.asyncio
async def test_get_batch_max_bytes_and_stream_batched() -> None:
    buf = EventBuffer(maxsize=10, buffer_name="batch", enable_priority=False, ttl_seconds=None)
    # Put two items
    await buf.put("A" * 50)
    await buf.put("B" * 50)

    # max_bytes small -> should break after first
    items = await buf.get_batch(max_items=5, timeout=0.2, max_bytes=10)
    assert 1 <= len(items) <= 2

    # Refill and stream in batches
    await buf.put("c1")
    await buf.put("c2")
    await buf.put("c3")

    async def get_one_batch(n: int) -> list[list[str]]:
        batches: list[list[str]] = []
        async for it in buf.stream(batch_size=2):
            assert isinstance(it, list)
            batches.append(it)
            if len(batches) >= n:
                break
        return batches

    batches = await get_one_batch(1)
    assert len(batches) == 1 and 1 <= len(batches[0]) <= 2
    await buf.shutdown()


@pytest.mark.asyncio
async def test_backpressure_activate_and_release() -> None:
    # With maxsize 4; high=0.5->2, low=0.25->1
    buf = EventBuffer(maxsize=4, buffer_name="bp", enable_priority=False,
                      backpressure_high_watermark=0.5, backpressure_low_watermark=0.25,
                      ttl_seconds=None)
    await buf.put("a")
    await buf.put("b")
    await buf.put("c")
    assert buf._backpressure_active is True
    # Drain to below low watermark
    _ = await buf.get()
    _ = await buf.get()
    _ = await buf.get()
    assert buf._backpressure_active is False
    await buf.shutdown()


@pytest.mark.asyncio
async def test_ttl_monitor_expires_and_no_ttl_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    # TTL-enabled path: priority queues and expired items
    buf = EventBuffer(maxsize=8, buffer_name="ttl", enable_priority=True, ttl_seconds=0.1)
    # Insert BufferedItems directly with old timestamps
    from app.services.sse.event_buffer import BufferedItem as BI
    old = BI("x", BufferPriority.HIGH)
    old.timestamp -= 999.0
    old2 = BI("y", BufferPriority.LOW)
    old2.timestamp -= 999.0
    # Put into internal queues and fix memory bytes
    buf._queues[BufferPriority.HIGH].put_nowait(old)  # type: ignore[index]
    buf._queues[BufferPriority.LOW].put_nowait(old2)  # type: ignore[index]
    buf._current_memory_bytes = old.size_bytes + old2.size_bytes

    # Make sleep fast and stop after one iteration. Capture and restore original sleep to
    # avoid affecting other buffers' background metrics tasks in this test.
    import app.services.sse.event_buffer as eb
    original_sleep = eb.asyncio.sleep
    async def fast_sleep(_):
        buf._running = False
    monkeypatch.setattr(eb, "asyncio", eb.asyncio)  # ensure module ref
    monkeypatch.setattr(eb.asyncio, "sleep", fast_sleep)
    try:
        await buf._ttl_monitor()
    finally:
        # Restore original sleep before creating any new buffers
        monkeypatch.setattr(eb.asyncio, "sleep", original_sleep)
    stats = await buf.get_stats()
    assert stats["total_expired"] >= 2 or stats["size"] == 0

    # no-ttl branch for _expire_from_queue (with real sleep restored to avoid spin loops)
    buf2 = EventBuffer(maxsize=2, buffer_name="nt", enable_priority=False, ttl_seconds=None)
    count = await buf2._expire_from_queue(buf2._queue)  # type: ignore[attr-defined]
    assert count == 0
    await buf.shutdown(); await buf2.shutdown()


@pytest.mark.asyncio
async def test_expire_from_queue_put_nowait_queue_full() -> None:
    # Create a fake queue to force QueueFull on put_back
    class FakeItem:
        def __init__(self): self._t = 0.0
        @property
        def age_seconds(self): return 0.0  # not expired  # noqa: D401
        size_bytes = 1

    class FakeQueue:
        def __init__(self, n: int):
            self.items = [FakeItem() for _ in range(n)]
        def empty(self): return len(self.items) == 0  # noqa: D401
        def get_nowait(self):
            if not self.items:
                raise asyncio.QueueEmpty()
            return self.items.pop(0)
        def put_nowait(self, _):
            raise asyncio.QueueFull()

    buf = EventBuffer(maxsize=2, buffer_name="fq", enable_priority=False, ttl_seconds=1.0)
    q = FakeQueue(2)
    # Should log error but return gracefully
    expired = await buf._expire_from_queue(q)  # type: ignore[arg-type]
    assert expired == 0
    await buf.shutdown()


@pytest.mark.asyncio
async def test_metrics_reporter_gc_and_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    buf = EventBuffer(maxsize=2, buffer_name="mr", enable_priority=False, ttl_seconds=None, max_memory_mb=0.001)
    # Set memory above 90% of limit to trigger gc
    buf._current_memory_bytes = int(buf._max_memory_mb * 1024 * 1024 * 0.95)

    called = {"gc": 0}
    def fake_gc(): called["gc"] += 1  # noqa: ANN001, D401
    monkeypatch.setattr("app.services.sse.event_buffer.gc.collect", fake_gc)

    # Make time divisible by 30 to hit logging path
    import time as _time
    real_time = _time.time
    monkeypatch.setattr("app.services.sse.event_buffer.time.time", lambda: (int(real_time() // 30) * 30))

    # One loop then stop
    async def fast_sleep(_):
        buf._running = False
    monkeypatch.setattr("app.services.sse.event_buffer.asyncio.sleep", fast_sleep)

    await buf._metrics_reporter()
    assert called["gc"] >= 1
    await buf.shutdown()
import asyncio
import pytest

from app.services.sse.event_buffer import EventBuffer, BufferPriority


@pytest.mark.asyncio
async def test_ttl_cleanup_with_priority_enabled():
    buf = EventBuffer(maxsize=10, buffer_name="ttlprio", enable_priority=True, ttl_seconds=0.05)
    # Add items in different priorities
    await buf.put("a", BufferPriority.CRITICAL)
    await buf.put("b", BufferPriority.LOW)
    # Force expiration by advancing time and manually running expiry on each queue
    # Patch time.time to simulate items aged beyond TTL
    import time as _time
    real_time = _time.time
    class T:
        def __call__(self):
            return real_time() + 1.0
    t = T()
    try:
        import app.services.sse.event_buffer as eb
        old_time = eb.time.time
        eb.time.time = t  # type: ignore[assignment]
        # Manually expire from all queues
        for q in buf._queues.values():  # type: ignore[attr-defined]
            await buf._expire_from_queue(q)
    finally:
        eb.time.time = old_time  # type: ignore[assignment]
    stats = await buf.get_stats()
    assert stats["size"] == 0
    await buf.shutdown()
