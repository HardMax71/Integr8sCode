from typing import NoReturn

import pytest
from app.core.metrics import (
    ConnectionMetrics,
    CoordinatorMetrics,
    DatabaseMetrics,
    DLQMetrics,
    EventMetrics,
    ExecutionMetrics,
    HealthMetrics,
    KubernetesMetrics,
    NotificationMetrics,
    RateLimitMetrics,
    ReplayMetrics,
    SecurityMetrics,
)
from app.settings import Settings


# Metrics fixtures - provided via DI, not global context
@pytest.fixture
def connection_metrics(test_settings: Settings) -> ConnectionMetrics:
    return ConnectionMetrics(test_settings)


@pytest.fixture
def coordinator_metrics(test_settings: Settings) -> CoordinatorMetrics:
    return CoordinatorMetrics(test_settings)


@pytest.fixture
def database_metrics(test_settings: Settings) -> DatabaseMetrics:
    return DatabaseMetrics(test_settings)


@pytest.fixture
def dlq_metrics(test_settings: Settings) -> DLQMetrics:
    return DLQMetrics(test_settings)


@pytest.fixture
def event_metrics(test_settings: Settings) -> EventMetrics:
    return EventMetrics(test_settings)


@pytest.fixture
def execution_metrics(test_settings: Settings) -> ExecutionMetrics:
    return ExecutionMetrics(test_settings)


@pytest.fixture
def health_metrics(test_settings: Settings) -> HealthMetrics:
    return HealthMetrics(test_settings)


@pytest.fixture
def kubernetes_metrics(test_settings: Settings) -> KubernetesMetrics:
    return KubernetesMetrics(test_settings)


@pytest.fixture
def notification_metrics(test_settings: Settings) -> NotificationMetrics:
    return NotificationMetrics(test_settings)


@pytest.fixture
def rate_limit_metrics(test_settings: Settings) -> RateLimitMetrics:
    return RateLimitMetrics(test_settings)


@pytest.fixture
def replay_metrics(test_settings: Settings) -> ReplayMetrics:
    return ReplayMetrics(test_settings)


@pytest.fixture
def security_metrics(test_settings: Settings) -> SecurityMetrics:
    return SecurityMetrics(test_settings)


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
