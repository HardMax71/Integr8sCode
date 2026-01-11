import logging
from collections.abc import Generator
from typing import NoReturn

import pytest
from app.core.metrics.connections import ConnectionMetrics
from app.core.metrics.context import MetricsContext
from app.core.metrics.coordinator import CoordinatorMetrics
from app.core.metrics.database import DatabaseMetrics
from app.core.metrics.dlq import DLQMetrics
from app.core.metrics.events import EventMetrics
from app.core.metrics.execution import ExecutionMetrics
from app.core.metrics.health import HealthMetrics
from app.core.metrics.kubernetes import KubernetesMetrics
from app.core.metrics.notifications import NotificationMetrics
from app.core.metrics.rate_limit import RateLimitMetrics
from app.core.metrics.replay import ReplayMetrics
from app.core.metrics.security import SecurityMetrics
from app.settings import Settings

_unit_test_logger = logging.getLogger("test.unit")


@pytest.fixture(scope="session", autouse=True)
def init_metrics_for_unit_tests(test_settings: Settings) -> Generator[None, None, None]:
    """Initialize all metrics context for unit tests."""
    MetricsContext.initialize_all(
        _unit_test_logger,
        connection=ConnectionMetrics(test_settings),
        coordinator=CoordinatorMetrics(test_settings),
        database=DatabaseMetrics(test_settings),
        dlq=DLQMetrics(test_settings),
        event=EventMetrics(test_settings),
        execution=ExecutionMetrics(test_settings),
        health=HealthMetrics(test_settings),
        kubernetes=KubernetesMetrics(test_settings),
        notification=NotificationMetrics(test_settings),
        rate_limit=RateLimitMetrics(test_settings),
        replay=ReplayMetrics(test_settings),
        security=SecurityMetrics(test_settings),
    )
    yield
    MetricsContext.reset_all(_unit_test_logger)


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
