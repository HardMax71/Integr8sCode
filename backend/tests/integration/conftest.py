"""Integration tests conftest."""
import uuid
from collections.abc import Callable

import pytest


@pytest.fixture
def unique_id(request: pytest.FixtureRequest) -> Callable[[str], str]:
    """Generate unique IDs with a prefix for test isolation.

    Each call returns a new unique ID. The test name prefix ensures
    isolation between tests; the counter ensures uniqueness within a test.

    Usage:
        def test_something(unique_id):
            exec_id = unique_id("exec-")  # exec-test_somethin-a1b2-0
            event_id = unique_id("evt-")  # evt-test_somethin-a1b2-1
    """
    base = f"{request.node.name[:15]}-{uuid.uuid4().hex[:4]}"
    counter = [0]  # Mutable container for closure

    def _make(prefix: str = "") -> str:
        result = f"{prefix}{base}-{counter[0]}"
        counter[0] += 1
        return result

    return _make
