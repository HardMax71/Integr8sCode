import logging

import pytest
from app.core.metrics import ConnectionMetrics
from app.services.sse.sse_connection_registry import SSEConnectionRegistry

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.services.sse.connection_registry")


@pytest.mark.asyncio
async def test_register_and_unregister(connection_metrics: ConnectionMetrics) -> None:
    """Test basic connection registration and unregistration."""
    registry = SSEConnectionRegistry(
        logger=_test_logger,
        connection_metrics=connection_metrics,
    )

    # Initially empty
    assert registry.get_connection_count() == 0
    assert registry.get_execution_count() == 0

    # Register connections
    await registry.register_connection("exec-1", "conn-1")
    assert registry.get_connection_count() == 1
    assert registry.get_execution_count() == 1

    await registry.register_connection("exec-1", "conn-2")
    assert registry.get_connection_count() == 2
    assert registry.get_execution_count() == 1  # Same execution

    await registry.register_connection("exec-2", "conn-3")
    assert registry.get_connection_count() == 3
    assert registry.get_execution_count() == 2

    # Unregister
    await registry.unregister_connection("exec-1", "conn-1")
    assert registry.get_connection_count() == 2
    assert registry.get_execution_count() == 2

    await registry.unregister_connection("exec-1", "conn-2")
    assert registry.get_connection_count() == 1
    assert registry.get_execution_count() == 1  # exec-1 removed

    await registry.unregister_connection("exec-2", "conn-3")
    assert registry.get_connection_count() == 0
    assert registry.get_execution_count() == 0


@pytest.mark.asyncio
async def test_unregister_nonexistent(connection_metrics: ConnectionMetrics) -> None:
    """Test unregistering a connection that doesn't exist."""
    registry = SSEConnectionRegistry(
        logger=_test_logger,
        connection_metrics=connection_metrics,
    )

    # Should not raise
    await registry.unregister_connection("nonexistent", "conn-1")
    assert registry.get_connection_count() == 0


@pytest.mark.asyncio
async def test_duplicate_registration(connection_metrics: ConnectionMetrics) -> None:
    """Test registering the same connection twice."""
    registry = SSEConnectionRegistry(
        logger=_test_logger,
        connection_metrics=connection_metrics,
    )

    await registry.register_connection("exec-1", "conn-1")
    await registry.register_connection("exec-1", "conn-1")  # Duplicate

    # Set behavior - duplicates ignored
    assert registry.get_connection_count() == 1
