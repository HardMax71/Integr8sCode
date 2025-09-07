import asyncio

import pytest

from app.services.sse.sse_shutdown_manager import SSEShutdownManager


class DummyRouter:
    def __init__(self): self.stopped = False
    async def stop(self): self.stopped = True  # noqa: ANN001


@pytest.mark.asyncio
async def test_shutdown_graceful_notify_and_drain():
    mgr = SSEShutdownManager(drain_timeout=1.0, notification_timeout=0.01, force_close_timeout=0.1)

    # Register two connections and arrange that they unregister when notified
    ev1 = await mgr.register_connection("e1", "c1")
    ev2 = await mgr.register_connection("e1", "c2")
    assert ev1 is not None and ev2 is not None

    async def on_shutdown(event, cid):  # noqa: ANN001
        await asyncio.wait_for(event.wait(), timeout=0.5)
        await mgr.unregister_connection("e1", cid)

    t1 = asyncio.create_task(on_shutdown(ev1, "c1"))
    t2 = asyncio.create_task(on_shutdown(ev2, "c2"))

    await mgr.initiate_shutdown()
    done = await mgr.wait_for_shutdown(timeout=1.0)
    assert done is True
    status = mgr.get_shutdown_status()
    assert status["phase"] == "complete"
    await asyncio.gather(t1, t2)


@pytest.mark.asyncio
async def test_shutdown_force_close_calls_router_stop_and_rejects_new():
    mgr = SSEShutdownManager(drain_timeout=0.01, notification_timeout=0.01, force_close_timeout=0.01)
    router = DummyRouter()
    mgr.set_router(router)

    # Register a connection but never unregister -> force close path
    ev = await mgr.register_connection("e1", "c1")
    assert ev is not None

    # Initiate shutdown
    await mgr.initiate_shutdown()
    assert router.stopped is True
    assert mgr.is_shutting_down() is True
    status = mgr.get_shutdown_status()
    assert status["draining_connections"] == 0

    # New connections should be rejected
    ev2 = await mgr.register_connection("e2", "c2")
    assert ev2 is None

import asyncio
import pytest

from app.services.sse.sse_shutdown_manager import SSEShutdownManager


@pytest.mark.asyncio
async def test_get_shutdown_status_transitions():
    m = SSEShutdownManager(drain_timeout=0.01, notification_timeout=0.0, force_close_timeout=0.0)
    st0 = m.get_shutdown_status()
    assert st0["phase"] == "ready"
    await m.initiate_shutdown()
    st1 = m.get_shutdown_status()
    assert st1["phase"] in ("draining", "complete", "closing", "notifying")

