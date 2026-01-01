import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load unit test env
unit_env = Path(__file__).parent / ".env.unit"
load_dotenv(unit_env, override=True)


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
