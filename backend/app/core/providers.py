import logging
from typing import AsyncIterator

import redis.asyncio as redis
from dishka import Provider, Scope, from_context, provide
from pymongo.asynchronous.mongo_client import AsyncMongoClient

from app.core.database_context import Database
from app.core.k8s_clients import K8sClients, close_k8s_clients, create_k8s_clients
from app.core.logging import setup_logger
from app.core.metrics import (
    CoordinatorMetrics,
    DatabaseMetrics,
    DLQMetrics,
    ExecutionMetrics,
    HealthMetrics,
    KubernetesMetrics,
    NotificationMetrics,
    ReplayMetrics,
    SecurityMetrics,
)
from app.core.metrics.connections import ConnectionMetrics
from app.core.metrics.events import EventMetrics
from app.core.metrics.rate_limit import RateLimitMetrics
from app.core.tracing import TracerManager
from app.db.repositories import (
    EventRepository,
    ExecutionRepository,
    NotificationRepository,
    SagaRepository,
    SavedScriptRepository,
    SSERepository,
    UserRepository,
)
from app.db.repositories.admin.admin_events_repository import AdminEventsRepository
from app.db.repositories.admin.admin_settings_repository import AdminSettingsRepository
from app.db.repositories.admin.admin_user_repository import AdminUserRepository
from app.db.repositories.dlq_repository import DLQRepository
from app.db.repositories.replay_repository import ReplayRepository
from app.db.repositories.resource_allocation_repository import ResourceAllocationRepository
from app.db.repositories.user_settings_repository import UserSettingsRepository
from app.dlq.manager import DLQManager, create_dlq_manager
from app.domain.enums.kafka import KafkaTopic
from app.domain.saga.models import SagaConfig
from app.events.core import ProducerConfig, UnifiedProducer
from app.events.event_store import EventStore, create_event_store
from app.events.event_store_consumer import EventStoreConsumer, create_event_store_consumer
from app.events.schema.schema_registry import SchemaRegistryManager, create_schema_registry_manager
from app.infrastructure.kafka.topics import get_all_topics
from app.services.admin import AdminEventsService, AdminSettingsService, AdminUserService
from app.services.auth_service import AuthService
from app.services.coordinator.coordinator import ExecutionCoordinator
from app.services.event_bus import EventBusManager
from app.services.event_replay.replay_service import EventReplayService
from app.services.event_service import EventService
from app.services.execution_service import ExecutionService
from app.services.grafana_alert_processor import GrafanaAlertProcessor
from app.services.idempotency import IdempotencyConfig, IdempotencyManager
from app.services.idempotency.idempotency_manager import create_idempotency_manager
from app.services.idempotency.redis_repository import RedisIdempotencyRepository
from app.services.k8s_worker.config import K8sWorkerConfig
from app.services.k8s_worker.worker import KubernetesWorker
from app.services.kafka_event_service import KafkaEventService
from app.services.notification_service import NotificationService
from app.services.pod_monitor.config import PodMonitorConfig
from app.services.pod_monitor.monitor import PodMonitor
from app.services.rate_limit_service import RateLimitService
from app.services.replay_service import ReplayService
from app.services.saga import SagaOrchestrator, create_saga_orchestrator
from app.services.saga.saga_service import SagaService
from app.services.saved_script_service import SavedScriptService
from app.services.sse.kafka_redis_bridge import SSEKafkaRedisBridge, create_sse_kafka_redis_bridge
from app.services.sse.redis_bus import SSERedisBus
from app.services.sse.sse_service import SSEService
from app.services.sse.sse_shutdown_manager import SSEShutdownManager, create_sse_shutdown_manager
from app.services.user_settings_service import UserSettingsService
from app.settings import Settings


class SettingsProvider(Provider):
    """Provides Settings from context (passed to make_async_container)."""

    settings = from_context(provides=Settings, scope=Scope.APP)


class LoggingProvider(Provider):
    scope = Scope.APP

    @provide
    def get_logger(self, settings: Settings) -> logging.Logger:
        return setup_logger(settings.LOG_LEVEL)


class RedisProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_redis_client(self, settings: Settings, logger: logging.Logger) -> AsyncIterator[redis.Redis]:
        # Create Redis client - it will automatically use the current event loop
        client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD,
            ssl=settings.REDIS_SSL,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            decode_responses=settings.REDIS_DECODE_RESPONSES,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        # Test connection
        await client.ping()  # type: ignore[misc]  # redis-py dual sync/async return type
        logger.info(f"Redis connected: {settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}")
        try:
            yield client
        finally:
            await client.aclose()

    @provide
    def get_rate_limit_service(
        self, redis_client: redis.Redis, settings: Settings, rate_limit_metrics: RateLimitMetrics
    ) -> RateLimitService:
        return RateLimitService(redis_client, settings, rate_limit_metrics)


class DatabaseProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_database(self, settings: Settings, logger: logging.Logger) -> AsyncIterator[Database]:
        client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(
            settings.MONGODB_URL, tz_aware=True, serverSelectionTimeoutMS=5000
        )
        database = client[settings.DATABASE_NAME]
        logger.info(f"MongoDB connected: {settings.DATABASE_NAME}")
        try:
            yield database
        finally:
            await client.close()


class CoreServicesProvider(Provider):
    scope = Scope.APP

    @provide
    def get_tracer_manager(self, settings: Settings) -> TracerManager:
        return TracerManager(tracer_name=settings.TRACING_SERVICE_NAME)


class MessagingProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_kafka_producer(
        self, settings: Settings, schema_registry: SchemaRegistryManager, logger: logging.Logger
    ) -> AsyncIterator[UnifiedProducer]:
        config = ProducerConfig(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
        async with UnifiedProducer(config, schema_registry, settings, logger) as producer:
            yield producer

    @provide
    async def get_dlq_manager(
        self, settings: Settings, schema_registry: SchemaRegistryManager, logger: logging.Logger
    ) -> AsyncIterator[DLQManager]:
        async with create_dlq_manager(settings, schema_registry, logger) as manager:
            yield manager

    @provide
    def get_idempotency_repository(self, redis_client: redis.Redis) -> RedisIdempotencyRepository:
        return RedisIdempotencyRepository(redis_client, key_prefix="idempotency")

    @provide
    async def get_idempotency_manager(
        self, repo: RedisIdempotencyRepository, logger: logging.Logger
    ) -> AsyncIterator[IdempotencyManager]:
        manager = create_idempotency_manager(repository=repo, config=IdempotencyConfig(), logger=logger)
        await manager.initialize()
        try:
            yield manager
        finally:
            await manager.close()


class EventProvider(Provider):
    scope = Scope.APP

    @provide
    def get_schema_registry(self, settings: Settings, logger: logging.Logger) -> SchemaRegistryManager:
        return create_schema_registry_manager(settings, logger)

    @provide
    async def get_event_store(self, schema_registry: SchemaRegistryManager, logger: logging.Logger) -> EventStore:
        store = create_event_store(schema_registry=schema_registry, logger=logger, ttl_days=90)
        return store

    @provide
    async def get_event_store_consumer(
        self,
        event_store: EventStore,
        schema_registry: SchemaRegistryManager,
        settings: Settings,
        kafka_producer: UnifiedProducer,
        logger: logging.Logger,
    ) -> AsyncIterator[EventStoreConsumer]:
        topics = get_all_topics()
        async with create_event_store_consumer(
            event_store=event_store,
            topics=list(topics),
            schema_registry_manager=schema_registry,
            settings=settings,
            producer=kafka_producer,
            logger=logger,
        ) as consumer:
            yield consumer

    @provide
    async def get_event_bus_manager(self, logger: logging.Logger) -> AsyncIterator[EventBusManager]:
        manager = EventBusManager(logger)
        try:
            yield manager
        finally:
            await manager.close()


class KubernetesProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_k8s_clients(self, settings: Settings, logger: logging.Logger) -> AsyncIterator[K8sClients]:
        clients = create_k8s_clients(logger)
        try:
            yield clients
        finally:
            close_k8s_clients(clients)


class MetricsProvider(Provider):
    """Provides all metrics instances."""

    scope = Scope.APP

    @provide
    def get_event_metrics(self) -> EventMetrics:
        return EventMetrics()

    @provide
    def get_connection_metrics(self) -> ConnectionMetrics:
        return ConnectionMetrics()

    @provide
    def get_rate_limit_metrics(self) -> RateLimitMetrics:
        return RateLimitMetrics()

    @provide
    def get_execution_metrics(self) -> ExecutionMetrics:
        return ExecutionMetrics()

    @provide
    def get_database_metrics(self) -> DatabaseMetrics:
        return DatabaseMetrics()

    @provide
    def get_health_metrics(self) -> HealthMetrics:
        return HealthMetrics()

    @provide
    def get_kubernetes_metrics(self) -> KubernetesMetrics:
        return KubernetesMetrics()

    @provide
    def get_coordinator_metrics(self) -> CoordinatorMetrics:
        return CoordinatorMetrics()

    @provide
    def get_dlq_metrics(self) -> DLQMetrics:
        return DLQMetrics()

    @provide
    def get_notification_metrics(self) -> NotificationMetrics:
        return NotificationMetrics()

    @provide
    def get_replay_metrics(self) -> ReplayMetrics:
        return ReplayMetrics()

    @provide
    def get_security_metrics(self) -> SecurityMetrics:
        return SecurityMetrics()


class RepositoryProvider(Provider):
    """Provides all repository instances. Repositories are stateless facades over database operations."""

    scope = Scope.APP

    @provide
    def get_execution_repository(self, logger: logging.Logger) -> ExecutionRepository:
        return ExecutionRepository(logger)

    @provide
    def get_saga_repository(self) -> SagaRepository:
        return SagaRepository()

    @provide
    def get_resource_allocation_repository(self) -> ResourceAllocationRepository:
        return ResourceAllocationRepository()

    @provide
    def get_saved_script_repository(self) -> SavedScriptRepository:
        return SavedScriptRepository()

    @provide
    def get_dlq_repository(self, logger: logging.Logger) -> DLQRepository:
        return DLQRepository(logger)

    @provide
    def get_replay_repository(self, logger: logging.Logger) -> ReplayRepository:
        return ReplayRepository(logger)

    @provide
    def get_event_repository(self, logger: logging.Logger) -> EventRepository:
        return EventRepository(logger)

    @provide
    def get_user_settings_repository(self, logger: logging.Logger) -> UserSettingsRepository:
        return UserSettingsRepository(logger)

    @provide
    def get_admin_events_repository(self) -> AdminEventsRepository:
        return AdminEventsRepository()

    @provide
    def get_admin_settings_repository(self, logger: logging.Logger) -> AdminSettingsRepository:
        return AdminSettingsRepository(logger)

    @provide
    def get_admin_user_repository(self) -> AdminUserRepository:
        return AdminUserRepository()

    @provide
    def get_notification_repository(self, logger: logging.Logger) -> NotificationRepository:
        return NotificationRepository(logger)

    @provide
    def get_sse_repository(self) -> SSERepository:
        return SSERepository()

    @provide
    def get_user_repository(self) -> UserRepository:
        return UserRepository()


class SSEProvider(Provider):
    """Provides SSE (Server-Sent Events) related services."""

    scope = Scope.APP

    @provide
    async def get_sse_redis_bus(self, redis_client: redis.Redis, logger: logging.Logger) -> AsyncIterator[SSERedisBus]:
        bus = SSERedisBus(redis_client, logger)
        yield bus

    @provide
    async def get_sse_kafka_redis_bridge(
        self,
        schema_registry: SchemaRegistryManager,
        settings: Settings,
        event_metrics: EventMetrics,
        sse_redis_bus: SSERedisBus,
        logger: logging.Logger,
    ) -> AsyncIterator[SSEKafkaRedisBridge]:
        async with create_sse_kafka_redis_bridge(
            schema_registry=schema_registry,
            settings=settings,
            event_metrics=event_metrics,
            sse_bus=sse_redis_bus,
            logger=logger,
        ) as bridge:
            yield bridge

    @provide(scope=Scope.REQUEST)
    def get_sse_shutdown_manager(self, logger: logging.Logger) -> SSEShutdownManager:
        return create_sse_shutdown_manager(logger=logger)

    @provide(scope=Scope.REQUEST)
    def get_sse_service(
        self,
        sse_repository: SSERepository,
        router: SSEKafkaRedisBridge,
        sse_redis_bus: SSERedisBus,
        shutdown_manager: SSEShutdownManager,
        settings: Settings,
        logger: logging.Logger,
    ) -> SSEService:
        shutdown_manager.set_router(router)
        return SSEService(
            repository=sse_repository,
            router=router,
            sse_bus=sse_redis_bus,
            shutdown_manager=shutdown_manager,
            settings=settings,
            logger=logger,
        )


class AuthProvider(Provider):
    scope = Scope.APP

    @provide
    def get_auth_service(self, user_repository: UserRepository, logger: logging.Logger) -> AuthService:
        return AuthService(user_repository, logger)


class KafkaServicesProvider(Provider):
    """Provides Kafka-related event services used by both main app and workers."""

    scope = Scope.APP

    @provide
    def get_event_service(self, event_repository: EventRepository) -> EventService:
        return EventService(event_repository)

    @provide
    def get_kafka_event_service(
        self, event_repository: EventRepository, kafka_producer: UnifiedProducer, logger: logging.Logger
    ) -> KafkaEventService:
        return KafkaEventService(event_repository=event_repository, kafka_producer=kafka_producer, logger=logger)


class UserServicesProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_user_settings_service(
        self,
        repository: UserSettingsRepository,
        kafka_event_service: KafkaEventService,
        event_bus_manager: EventBusManager,
        logger: logging.Logger,
    ) -> UserSettingsService:
        service = UserSettingsService(repository, kafka_event_service, logger)
        await service.initialize(event_bus_manager)
        return service


class AdminServicesProvider(Provider):
    scope = Scope.APP

    @provide(scope=Scope.REQUEST)
    def get_admin_events_service(
        self,
        admin_events_repository: AdminEventsRepository,
        replay_service: ReplayService,
        logger: logging.Logger,
    ) -> AdminEventsService:
        return AdminEventsService(admin_events_repository, replay_service, logger)

    @provide
    def get_admin_settings_service(
        self,
        admin_settings_repository: AdminSettingsRepository,
        logger: logging.Logger,
    ) -> AdminSettingsService:
        return AdminSettingsService(admin_settings_repository, logger)

    @provide
    def get_notification_service(
        self,
        notification_repository: NotificationRepository,
        kafka_event_service: KafkaEventService,
        event_bus_manager: EventBusManager,
        schema_registry: SchemaRegistryManager,
        sse_redis_bus: SSERedisBus,
        settings: Settings,
        logger: logging.Logger,
    ) -> NotificationService:
        service = NotificationService(
            notification_repository=notification_repository,
            event_service=kafka_event_service,
            event_bus_manager=event_bus_manager,
            schema_registry_manager=schema_registry,
            sse_bus=sse_redis_bus,
            settings=settings,
            logger=logger,
        )
        service.initialize()
        return service

    @provide
    def get_grafana_alert_processor(
        self,
        notification_service: NotificationService,
        logger: logging.Logger,
    ) -> GrafanaAlertProcessor:
        return GrafanaAlertProcessor(notification_service, logger)


def _create_default_saga_config() -> SagaConfig:
    """Factory for default SagaConfig used by orchestrators."""
    return SagaConfig(
        name="main-orchestrator",
        timeout_seconds=300,
        max_retries=3,
        retry_delay_seconds=5,
        enable_compensation=True,
        store_events=True,
        publish_commands=True,
    )


# Standalone factory functions for lifecycle-managed services (eliminates duplication)
async def _provide_saga_orchestrator(
    saga_repository: SagaRepository,
    kafka_producer: UnifiedProducer,
    schema_registry: SchemaRegistryManager,
    settings: Settings,
    event_store: EventStore,
    idempotency_manager: IdempotencyManager,
    resource_allocation_repository: ResourceAllocationRepository,
    logger: logging.Logger,
) -> AsyncIterator[SagaOrchestrator]:
    """Shared factory for SagaOrchestrator with lifecycle management."""
    async with create_saga_orchestrator(
        saga_repository=saga_repository,
        producer=kafka_producer,
        schema_registry_manager=schema_registry,
        settings=settings,
        event_store=event_store,
        idempotency_manager=idempotency_manager,
        resource_allocation_repository=resource_allocation_repository,
        config=_create_default_saga_config(),
        logger=logger,
    ) as orchestrator:
        yield orchestrator


async def _provide_execution_coordinator(
    kafka_producer: UnifiedProducer,
    schema_registry: SchemaRegistryManager,
    settings: Settings,
    event_store: EventStore,
    execution_repository: ExecutionRepository,
    idempotency_manager: IdempotencyManager,
    logger: logging.Logger,
) -> AsyncIterator[ExecutionCoordinator]:
    """Shared factory for ExecutionCoordinator with lifecycle management."""
    async with ExecutionCoordinator(
        producer=kafka_producer,
        schema_registry_manager=schema_registry,
        settings=settings,
        event_store=event_store,
        execution_repository=execution_repository,
        idempotency_manager=idempotency_manager,
        logger=logger,
    ) as coordinator:
        yield coordinator


class BusinessServicesProvider(Provider):
    scope = Scope.REQUEST

    def __init__(self) -> None:
        super().__init__()
        # Register shared factory functions on instance (avoids warning about missing self)
        self.provide(_provide_saga_orchestrator)
        self.provide(_provide_execution_coordinator)

    @provide
    def get_saga_service(
        self,
        saga_repository: SagaRepository,
        execution_repository: ExecutionRepository,
        saga_orchestrator: SagaOrchestrator,
        logger: logging.Logger,
    ) -> SagaService:
        return SagaService(
            saga_repo=saga_repository,
            execution_repo=execution_repository,
            orchestrator=saga_orchestrator,
            logger=logger,
        )

    @provide
    def get_execution_service(
        self,
        execution_repository: ExecutionRepository,
        kafka_producer: UnifiedProducer,
        event_store: EventStore,
        settings: Settings,
        logger: logging.Logger,
    ) -> ExecutionService:
        return ExecutionService(
            execution_repo=execution_repository,
            producer=kafka_producer,
            event_store=event_store,
            settings=settings,
            logger=logger,
        )

    @provide
    def get_saved_script_service(
        self, saved_script_repository: SavedScriptRepository, logger: logging.Logger
    ) -> SavedScriptService:
        return SavedScriptService(saved_script_repository, logger)

    @provide
    async def get_replay_service(
        self,
        replay_repository: ReplayRepository,
        kafka_producer: UnifiedProducer,
        event_store: EventStore,
        logger: logging.Logger,
    ) -> ReplayService:
        event_replay_service = EventReplayService(
            repository=replay_repository, producer=kafka_producer, event_store=event_store, logger=logger
        )
        return ReplayService(replay_repository, event_replay_service, logger)

    @provide
    def get_admin_user_service(
        self,
        admin_user_repository: AdminUserRepository,
        event_service: EventService,
        execution_service: ExecutionService,
        rate_limit_service: RateLimitService,
        logger: logging.Logger,
    ) -> AdminUserService:
        return AdminUserService(
            user_repository=admin_user_repository,
            event_service=event_service,
            execution_service=execution_service,
            rate_limit_service=rate_limit_service,
            logger=logger,
        )


class CoordinatorProvider(Provider):
    scope = Scope.APP

    def __init__(self) -> None:
        super().__init__()
        self.provide(_provide_execution_coordinator)


class K8sWorkerProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_kubernetes_worker(
        self,
        kafka_producer: UnifiedProducer,
        schema_registry: SchemaRegistryManager,
        settings: Settings,
        event_store: EventStore,
        idempotency_manager: IdempotencyManager,
        logger: logging.Logger,
    ) -> AsyncIterator[KubernetesWorker]:
        config = K8sWorkerConfig()
        async with KubernetesWorker(
            config=config,
            producer=kafka_producer,
            schema_registry_manager=schema_registry,
            settings=settings,
            event_store=event_store,
            idempotency_manager=idempotency_manager,
            logger=logger,
        ) as worker:
            yield worker


class PodMonitorProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_pod_monitor(
        self,
        kafka_event_service: KafkaEventService,
        k8s_clients: K8sClients,
        logger: logging.Logger,
    ) -> AsyncIterator[PodMonitor]:
        config = PodMonitorConfig()
        async with PodMonitor(
            config=config,
            kafka_event_service=kafka_event_service,
            logger=logger,
            k8s_clients=k8s_clients,
        ) as monitor:
            yield monitor


class SagaOrchestratorProvider(Provider):
    scope = Scope.APP

    def __init__(self) -> None:
        super().__init__()
        self.provide(_provide_saga_orchestrator)


class EventReplayProvider(Provider):
    scope = Scope.APP

    @provide
    def get_event_replay_service(
        self,
        replay_repository: ReplayRepository,
        kafka_producer: UnifiedProducer,
        event_store: EventStore,
        logger: logging.Logger,
    ) -> EventReplayService:
        return EventReplayService(
            repository=replay_repository,
            producer=kafka_producer,
            event_store=event_store,
            logger=logger,
        )


class DLQProcessorProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_dlq_manager(
        self,
        settings: Settings,
        schema_registry: SchemaRegistryManager,
        logger: logging.Logger,
    ) -> AsyncIterator[DLQManager]:
        async with create_dlq_manager(
            settings=settings,
            schema_registry=schema_registry,
            logger=logger,
            dlq_topic=KafkaTopic.DEAD_LETTER_QUEUE,
            retry_topic_suffix="-retry",
        ) as manager:
            yield manager
