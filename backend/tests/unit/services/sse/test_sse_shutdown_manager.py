import asyncio
import pytest

pytestmark = pytest.mark.unit

from app.services.sse.sse_shutdown_manager import SSEShutdownManager


class _FakeRouter:
    def __init__(self) -> None:
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


@pytest.mark.asyncio
async def test_register_unregister_and_shutdown_flow() -> None:
    mgr = SSEShutdownManager(drain_timeout=0.5, notification_timeout=0.1, force_close_timeout=0.1)
    mgr.set_router(_FakeRouter())

    # Register two connections
    e1 = await mgr.register_connection("exec-1", "c1")
    e2 = await mgr.register_connection("exec-1", "c2")
    assert e1 is not None and e2 is not None

    # Start shutdown concurrently
    task = asyncio.create_task(mgr.initiate_shutdown())

    # After notify phase starts, set connection events and unregister to drain
    await asyncio.sleep(0.05)
    e1.set()  # tell client 1
    await mgr.unregister_connection("exec-1", "c1")
    e2.set()
    await mgr.unregister_connection("exec-1", "c2")

    await task
    assert mgr.get_shutdown_status()["complete"] is True


@pytest.mark.asyncio
async def test_reject_new_connection_during_shutdown() -> None:
    mgr = SSEShutdownManager(drain_timeout=0.1, notification_timeout=0.01, force_close_timeout=0.01)
    # Start shutdown
    t = asyncio.create_task(mgr.initiate_shutdown())
    await asyncio.sleep(0.01)

    # New registrations rejected
    denied = await mgr.register_connection("e", "c")
    assert denied is None
    await t
