import logging
from typing import AsyncGenerator, NoReturn

import pytest
import pytest_asyncio
from aiokafka import AIOKafkaProducer
from app.core.database_context import Database
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
from app.core.providers import (
    CoreServicesProvider,
    EventProvider,
    KafkaServicesProvider,
    LoggingProvider,
    MessagingProvider,
    MetricsProvider,
    RedisServicesProvider,
    RepositoryProvider,
    SettingsProvider,
)
from app.db.docs import ALL_DOCUMENTS
from app.db.repositories import (
    EventRepository,
    ExecutionRepository,
    SagaRepository,
    SSERepository,
)
from app.db.repositories.resource_allocation_repository import ResourceAllocationRepository
from app.events.core import UnifiedProducer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.kafka_event_service import KafkaEventService
from app.services.pod_monitor.config import PodMonitorConfig
from app.services.pod_monitor.event_mapper import PodEventMapper
from app.services.pod_monitor.monitor import PodMonitor
from app.settings import Settings
from beanie import init_beanie
from dishka import AsyncContainer, make_async_container

from tests.helpers.fakes import FakeBoundaryClientProvider, FakeDatabaseProvider, FakeSchemaRegistryProvider
from tests.helpers.fakes.kafka import FakeAIOKafkaProducer
from tests.helpers.k8s_fakes import FakeApi, FakeV1Api, FakeWatch, make_k8s_clients

_test_logger = logging.getLogger("test.unit")


@pytest_asyncio.fixture(scope="session")
async def unit_container(test_settings: Settings) -> AsyncGenerator[AsyncContainer, None]:
    """DI container for unit tests with fake boundary clients.

    Provides:
    - Fake Redis, Kafka, K8s, MongoDB (boundary clients)
    - Real metrics, repositories, services (internal)
    """
    container = make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        FakeBoundaryClientProvider(),
        FakeDatabaseProvider(),
        RedisServicesProvider(),
        MetricsProvider(),
        EventProvider(),
        FakeSchemaRegistryProvider(),  # Override real schema registry with fake
        MessagingProvider(),
        CoreServicesProvider(),
        KafkaServicesProvider(),
        RepositoryProvider(),
        context={Settings: test_settings},
    )

    db = await container.get(Database)
    await init_beanie(database=db, document_models=ALL_DOCUMENTS)

    yield container
    await container.close()


@pytest_asyncio.fixture
async def unit_scope(unit_container: AsyncContainer) -> AsyncGenerator[AsyncContainer, None]:
    """Request scope from unit test container."""
    async with unit_container() as scope:
        yield scope


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


@pytest_asyncio.fixture
async def saga_repository(unit_container: AsyncContainer) -> SagaRepository:
    return await unit_container.get(SagaRepository)


@pytest_asyncio.fixture
async def execution_repository(unit_container: AsyncContainer) -> ExecutionRepository:
    return await unit_container.get(ExecutionRepository)


@pytest_asyncio.fixture
async def event_repository(unit_container: AsyncContainer) -> EventRepository:
    return await unit_container.get(EventRepository)


@pytest_asyncio.fixture
async def sse_repository(unit_container: AsyncContainer) -> SSERepository:
    return await unit_container.get(SSERepository)


@pytest_asyncio.fixture
async def resource_allocation_repository(unit_container: AsyncContainer) -> ResourceAllocationRepository:
    return await unit_container.get(ResourceAllocationRepository)


@pytest_asyncio.fixture
async def unified_producer(unit_container: AsyncContainer) -> UnifiedProducer:
    return await unit_container.get(UnifiedProducer)


@pytest_asyncio.fixture
async def schema_registry(unit_container: AsyncContainer) -> SchemaRegistryManager:
    return await unit_container.get(SchemaRegistryManager)


@pytest_asyncio.fixture
async def test_logger(unit_container: AsyncContainer) -> logging.Logger:
    return await unit_container.get(logging.Logger)


@pytest_asyncio.fixture
async def kafka_event_service(unit_container: AsyncContainer) -> KafkaEventService:
    """Real KafkaEventService wired with fake backends."""
    return await unit_container.get(KafkaEventService)


@pytest_asyncio.fixture
async def fake_kafka_producer(unit_container: AsyncContainer) -> FakeAIOKafkaProducer:
    """Access to fake Kafka producer for verifying sent messages."""
    producer = await unit_container.get(AIOKafkaProducer)
    assert isinstance(producer, FakeAIOKafkaProducer)
    return producer


@pytest.fixture
def pod_monitor_config() -> PodMonitorConfig:
    return PodMonitorConfig()


@pytest.fixture
def k8s_v1() -> FakeV1Api:
    """Default fake CoreV1Api for tests."""
    v1, _ = make_k8s_clients()
    return v1


@pytest.fixture
def k8s_watch() -> FakeWatch:
    """Default fake Watch for tests."""
    _, watch = make_k8s_clients()
    return watch


@pytest_asyncio.fixture
async def pod_monitor(
        unit_container: AsyncContainer,
        pod_monitor_config: PodMonitorConfig,
        kubernetes_metrics: KubernetesMetrics,
        k8s_v1: FakeV1Api,
        k8s_watch: FakeWatch,
) -> PodMonitor:
    """Fully wired PodMonitor ready for testing."""
    kafka_service = await unit_container.get(KafkaEventService)
    event_mapper = PodEventMapper(logger=_test_logger, k8s_api=FakeApi("{}"))

    return PodMonitor(
        config=pod_monitor_config,
        kafka_event_service=kafka_service,
        logger=_test_logger,
        k8s_v1=k8s_v1,
        k8s_watch=k8s_watch,
        event_mapper=event_mapper,
        kubernetes_metrics=kubernetes_metrics,
    )


@pytest.fixture
def db() -> NoReturn:
    raise RuntimeError("Use 'unit_container' fixture for DB access in unit tests")


@pytest.fixture
def redis_client() -> NoReturn:
    raise RuntimeError("Use 'unit_container' fixture for Redis in unit tests")


@pytest.fixture
def client() -> NoReturn:
    raise RuntimeError("Unit tests should not use HTTP client - move to integration/")


@pytest.fixture
def app() -> NoReturn:
    raise RuntimeError("Unit tests should not use full app - move to integration/")
