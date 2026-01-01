"""Unit test configuration.

Unit tests should NOT access real infrastructure (DB, Redis, HTTP).
These fixtures raise errors to catch accidental usage.
"""
import pytest


@pytest.fixture
def db():
    raise RuntimeError("Unit tests should not access DB - use mocks or move to integration/")


@pytest.fixture
def redis_client():
    raise RuntimeError("Unit tests should not access Redis - use mocks or move to integration/")


@pytest.fixture
def client():
    raise RuntimeError("Unit tests should not use HTTP client - use mocks or move to integration/")


@pytest.fixture
def app():
    raise RuntimeError("Unit tests should not use full app - use mocks or move to integration/")
