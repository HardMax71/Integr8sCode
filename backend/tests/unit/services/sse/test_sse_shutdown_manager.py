import asyncio
import logging

import pytest
from app.core.lifecycle import LifecycleEnabled
from app.core.metrics import ConnectionMetrics
from app.services.sse.sse_shutdown_manager import SSEShutdownManager

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.services.sse.sse_shutdown_manager")


class _FakeRouter(LifecycleEnabled):
    """Fake router that tracks whether aclose was called."""

    def __init__(self) -> None:
        super().__init__()
        self.stopped = False
        self._lifecycle_started = True  # Simulate already-started router

    async def _on_stop(self) -> None:
        self.stopped = True


@pytest.mark.asyncio
async def test_register_unregister_and_shutdown_flow(connection_metrics: ConnectionMetrics) -> None:
    mgr = SSEShutdownManager(drain_timeout=0.5, notification_timeout=0.1, force_close_timeout=0.1, logger=_test_logger, connection_metrics=connection_metrics)
    mgr.set_router(_FakeRouter())

    # Register two connections
    e1 = await mgr.register_connection("exec-1", "c1")
    e2 = await mgr.register_connection("exec-1", "c2")
    assert e1 is not None and e2 is not None

    # Start shutdown - it will block waiting for connections to drain
    shutdown_task = asyncio.create_task(mgr.initiate_shutdown())

    # Give shutdown task a chance to start and enter drain phase
    await asyncio.sleep(0)  # Yield control once

    # Simulate clients acknowledging and disconnecting
    e1.set()
    await mgr.unregister_connection("exec-1", "c1")
    e2.set()
    await mgr.unregister_connection("exec-1", "c2")

    # Now shutdown can complete
    await shutdown_task
    assert mgr.get_shutdown_status().complete is True


@pytest.mark.asyncio
async def test_reject_new_connection_during_shutdown(connection_metrics: ConnectionMetrics) -> None:
    mgr = SSEShutdownManager(drain_timeout=0.5, notification_timeout=0.01, force_close_timeout=0.01,
                             logger=_test_logger, connection_metrics=connection_metrics)
    # Pre-register one active connection - shutdown will block waiting for it
    e = await mgr.register_connection("e", "c0")
    assert e is not None

    # Start shutdown task - it sets _shutdown_initiated immediately then blocks on drain
    shutdown_task = asyncio.create_task(mgr.initiate_shutdown())

    # Yield control so shutdown task can start and set _shutdown_initiated
    await asyncio.sleep(0)

    # Shutdown is now initiated (blocking on drain), new registrations should be rejected
    assert mgr.is_shutting_down() is True
    denied = await mgr.register_connection("e", "c1")
    assert denied is None

    # Clean up - disconnect the blocking connection so shutdown can complete
    e.set()
    await mgr.unregister_connection("e", "c0")
    await shutdown_task
