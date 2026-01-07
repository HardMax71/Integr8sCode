import asyncio
import logging

import backoff
import pytest
from app.services.sse.sse_shutdown_manager import SSEShutdownManager

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.services.sse.sse_shutdown_manager")


class _FakeRouter:
    def __init__(self) -> None:
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


@pytest.mark.asyncio
async def test_register_unregister_and_shutdown_flow() -> None:
    mgr = SSEShutdownManager(drain_timeout=0.5, notification_timeout=0.1, force_close_timeout=0.1, logger=_test_logger)
    mgr.set_router(_FakeRouter())  # type: ignore[arg-type]

    # Register two connections
    e1 = await mgr.register_connection("exec-1", "c1")
    e2 = await mgr.register_connection("exec-1", "c2")
    assert e1 is not None and e2 is not None

    # Start shutdown concurrently
    task = asyncio.create_task(mgr.initiate_shutdown())

    # Wait until manager enters NOTIFYING phase (event-driven)
    @backoff.on_exception(backoff.constant, AssertionError, max_time=1.0, interval=0.02)
    async def _wait_notifying() -> None:
        assert mgr.get_shutdown_status().phase == "notifying"

    await _wait_notifying()

    # Simulate clients acknowledging and disconnecting
    e1.set()
    await mgr.unregister_connection("exec-1", "c1")
    e2.set()
    await mgr.unregister_connection("exec-1", "c2")

    await task
    assert mgr.get_shutdown_status().complete is True


@pytest.mark.asyncio
async def test_reject_new_connection_during_shutdown() -> None:
    mgr = SSEShutdownManager(
        drain_timeout=0.1, notification_timeout=0.01, force_close_timeout=0.01, logger=_test_logger
    )
    # Pre-register one active connection to reflect realistic state
    e = await mgr.register_connection("e", "c0")
    assert e is not None

    # Start shutdown and wait until initiated
    t = asyncio.create_task(mgr.initiate_shutdown())

    @backoff.on_exception(backoff.constant, AssertionError, max_time=1.0, interval=0.02)
    async def _wait_initiated() -> None:
        assert mgr.is_shutting_down() is True

    await _wait_initiated()

    # New registrations rejected once shutdown initiated
    denied = await mgr.register_connection("e", "c1")
    assert denied is None
    await t
