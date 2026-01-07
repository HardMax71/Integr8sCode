"""Unit test configuration.

Unit tests should NOT access real infrastructure (DB, Redis, HTTP).
These fixtures raise errors to catch accidental usage.
"""
from typing import NoReturn

import pytest


@pytest.fixture
def db() -> NoReturn:
    raise RuntimeError("Unit tests should not access DB - use mocks or move to integration/")


@pytest.fixture
def redis_client() -> NoReturn:
    raise RuntimeError("Unit tests should not access Redis - use mocks or move to integration/")


@pytest.fixture
def client() -> NoReturn:
    raise RuntimeError("Unit tests should not use HTTP client - use mocks or move to integration/")


@pytest.fixture
def app() -> NoReturn:
    raise RuntimeError("Unit tests should not use full app - use mocks or move to integration/")
