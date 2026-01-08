"""Integration tests conftest."""
import uuid
from collections.abc import Callable

import pytest


@pytest.fixture
def unique_id(request: pytest.FixtureRequest) -> Callable[[str], str]:
    """Generate unique IDs with a prefix for test isolation.

    Usage:
        def test_something(unique_id):
            exec_id = unique_id("exec-")
            event_id = unique_id("evt-")
    """
    suffix = f"{request.node.name[:15]}-{uuid.uuid4().hex[:8]}"

    def _make(prefix: str = "") -> str:
        return f"{prefix}{suffix}"

    return _make
