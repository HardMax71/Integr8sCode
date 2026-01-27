import logging
from typing import AsyncIterator

import redis.asyncio as redis
from aiokafka import AIOKafkaProducer
from dishka import Provider, Scope, from_context, provide
from pymongo.asynchronous.mongo_client import AsyncMongoClient

from app.core.database_context import Database
from app.core.k8s_clients import K8sClients, close_k8s_clients, create_k8s_clients
from app.core.logging import setup_logger
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
from app.core.security import SecurityService
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
from app.db.repositories.execution_queue_repository import ExecutionQueueRepository
from app.db.repositories.execution_state_repository import ExecutionStateRepository
from app.db.repositories.pod_state_repository import PodStateRepository
from app.db.repositories.replay_repository import ReplayRepository
from app.db.repositories.resource_allocation_repository import ResourceAllocationRepository
from app.db.repositories.resource_repository import ResourceRepository
from app.db.repositories.user_settings_repository import UserSettingsRepository
from app.dlq.manager import DLQManager
from app.domain.saga.models import SagaConfig
from app.events.core import ProducerMetrics, UnifiedProducer
from app.events.event_store import EventStore, create_event_store
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.admin import AdminEventsService, AdminSettingsService, AdminUserService
from app.services.auth_service import AuthService
from app.services.coordinator.coordinator import ExecutionCoordinator
from app.services.event_bus import EventBus
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
from app.services.pod_monitor.event_mapper import PodEventMapper
from app.services.pod_monitor.monitor import PodMonitor
from app.services.rate_limit_service import RateLimitService
from app.services.replay_service import ReplayService
from app.services.result_processor.resource_cleaner import ResourceCleaner
from app.services.saga import SagaOrchestrator
from app.services.saga.saga_service import SagaService
from app.services.saved_script_service import SavedScriptService
from app.services.sse.kafka_redis_bridge import SSEKafkaRedisBridge
from app.services.sse.redis_bus import SSERedisBus
from app.services.sse.sse_service import SSEService
from app.services.sse.sse_shutdown_manager import SSEShutdownManager
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


class RedisRepositoryProvider(Provider):
    """Provides Redis-backed state repositories for stateless services."""

    scope = Scope.APP

    @provide
    def get_execution_state_repository(
            self, redis_client: redis.Redis, logger: logging.Logger
    ) -> ExecutionStateRepository:
        return ExecutionStateRepository(redis_client, logger)

    @provide
    def get_execution_queue_repository(
            self, redis_client: redis.Redis, logger: logging.Logger, settings: Settings
    ) -> ExecutionQueueRepository:
        return ExecutionQueueRepository(
            redis_client,
            logger,
            max_queue_size=10000,
            max_executions_per_user=100,
        )

    @provide
    async def get_resource_repository(
            self, redis_client: redis.Redis, logger: logging.Logger, settings: Settings
    ) -> ResourceRepository:
        repo = ResourceRepository(
            redis_client,
            logger,
            total_cpu_cores=32.0,
            total_memory_mb=65536,
        )
        await repo.initialize()
        return repo

    @provide
    def get_pod_state_repository(
            self, redis_client: redis.Redis, logger: logging.Logger
    ) -> PodStateRepository:
        return PodStateRepository(redis_client, logger)


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
    def get_security_service(self, settings: Settings) -> SecurityService:
        return SecurityService(settings)

    @provide
    def get_tracer_manager(self, settings: Settings) -> TracerManager:
        return TracerManager(tracer_name=settings.TRACING_SERVICE_NAME)


class KafkaProvider(Provider):
    """Provides Kafka producer - low-level AIOKafkaProducer for DI."""

    scope = Scope.APP

    @provide
    async def get_aiokafka_producer(
            self, settings: Settings, logger: logging.Logger
    ) -> AsyncIterator[AIOKafkaProducer]:
        producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            acks="all",
            enable_idempotence=True,
            max_request_size=10 * 1024 * 1024,  # 10MB
        )
        await producer.start()
        logger.info(f"Kafka producer started: {settings.KAFKA_BOOTSTRAP_SERVERS}")
        try:
            yield producer
        finally:
            await producer.stop()


class MessagingProvider(Provider):
    scope = Scope.APP

    @provide
    def get_producer_metrics(self) -> ProducerMetrics:
        return ProducerMetrics()

    @provide
    def get_unified_producer(
            self,
            aiokafka_producer: AIOKafkaProducer,
            schema_registry: SchemaRegistryManager,
            logger: logging.Logger,
            event_metrics: EventMetrics,
            producer_metrics: ProducerMetrics,
    ) -> UnifiedProducer:
        return UnifiedProducer(
            producer=aiokafka_producer,
            schema_registry_manager=schema_registry,
            logger=logger,
            event_metrics=event_metrics,
            producer_metrics=producer_metrics,
        )

    @provide
    def get_dlq_manager(
            self,
            settings: Settings,
            aiokafka_producer: AIOKafkaProducer,
            schema_registry: SchemaRegistryManager,
            logger: logging.Logger,
            dlq_metrics: DLQMetrics,
    ) -> DLQManager:
        return DLQManager(
            settings=settings,
            producer=aiokafka_producer,
            schema_registry=schema_registry,
            logger=logger,
            dlq_metrics=dlq_metrics,
        )

    @provide
    def get_idempotency_repository(self, redis_client: redis.Redis) -> RedisIdempotencyRepository:
        return RedisIdempotencyRepository(redis_client, key_prefix="idempotency")

    @provide
    async def get_idempotency_manager(
            self, repo: RedisIdempotencyRepository, logger: logging.Logger, database_metrics: DatabaseMetrics
    ) -> AsyncIterator[IdempotencyManager]:
        manager = create_idempotency_manager(
            repository=repo, config=IdempotencyConfig(), logger=logger, database_metrics=database_metrics
        )
        await manager.initialize()
        try:
            yield manager
        finally:
            await manager.close()


class EventProvider(Provider):
    scope = Scope.APP

    @provide
    def get_schema_registry(self, settings: Settings, logger: logging.Logger) -> SchemaRegistryManager:
        return SchemaRegistryManager(settings, logger)

    @provide
    def get_event_store(
            self, schema_registry: SchemaRegistryManager, logger: logging.Logger, event_metrics: EventMetrics
    ) -> EventStore:
        return create_event_store(
            schema_registry=schema_registry, logger=logger, event_metrics=event_metrics, ttl_days=90
        )

    @provide
    def get_event_bus(
            self,
            aiokafka_producer: AIOKafkaProducer,
            settings: Settings,
            logger: logging.Logger,
            connection_metrics: ConnectionMetrics,
    ) -> EventBus:
        return EventBus(
            producer=aiokafka_producer,
            settings=settings,
            logger=logger,
            connection_metrics=connection_metrics,
        )


class KubernetesProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_k8s_clients(self, settings: Settings, logger: logging.Logger) -> AsyncIterator[K8sClients]:
        clients = create_k8s_clients(logger, kubeconfig_path=settings.KUBERNETES_CONFIG_PATH)
        try:
            yield clients
        finally:
            close_k8s_clients(clients)


class ResourceCleanerProvider(Provider):
    scope = Scope.APP

    @provide
    def get_resource_cleaner(self, k8s_clients: K8sClients, logger: logging.Logger) -> ResourceCleaner:
        return ResourceCleaner(k8s_clients=k8s_clients, logger=logger)


class MetricsProvider(Provider):
    """Provides all metrics instances via DI (no contextvars needed)."""

    scope = Scope.APP

    @provide
    def get_event_metrics(self, settings: Settings) -> EventMetrics:
        return EventMetrics(settings)

    @provide
    def get_connection_metrics(self, settings: Settings) -> ConnectionMetrics:
        return ConnectionMetrics(settings)

    @provide
    def get_rate_limit_metrics(self, settings: Settings) -> RateLimitMetrics:
        return RateLimitMetrics(settings)

    @provide
    def get_execution_metrics(self, settings: Settings) -> ExecutionMetrics:
        return ExecutionMetrics(settings)

    @provide
    def get_database_metrics(self, settings: Settings) -> DatabaseMetrics:
        return DatabaseMetrics(settings)

    @provide
    def get_health_metrics(self, settings: Settings) -> HealthMetrics:
        return HealthMetrics(settings)

    @provide
    def get_kubernetes_metrics(self, settings: Settings) -> KubernetesMetrics:
        return KubernetesMetrics(settings)

    @provide
    def get_coordinator_metrics(self, settings: Settings) -> CoordinatorMetrics:
        return CoordinatorMetrics(settings)

    @provide
    def get_dlq_metrics(self, settings: Settings) -> DLQMetrics:
        return DLQMetrics(settings)

    @provide
    def get_notification_metrics(self, settings: Settings) -> NotificationMetrics:
        return NotificationMetrics(settings)

    @provide
    def get_replay_metrics(self, settings: Settings) -> ReplayMetrics:
        return ReplayMetrics(settings)

    @provide
    def get_security_metrics(self, settings: Settings) -> SecurityMetrics:
        return SecurityMetrics(settings)


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
    def get_admin_user_repository(self, security_service: SecurityService) -> AdminUserRepository:
        return AdminUserRepository(security_service)

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
    def get_sse_redis_bus(self, redis_client: redis.Redis, logger: logging.Logger) -> SSERedisBus:
        return SSERedisBus(redis_client, logger)

    @provide
    def get_sse_kafka_redis_bridge(
            self,
            sse_redis_bus: SSERedisBus,
            logger: logging.Logger,
    ) -> SSEKafkaRedisBridge:
        return SSEKafkaRedisBridge(
            sse_bus=sse_redis_bus,
            logger=logger,
        )

    @provide(scope=Scope.REQUEST)
    def get_sse_shutdown_manager(
            self, logger: logging.Logger, connection_metrics: ConnectionMetrics
    ) -> SSEShutdownManager:
        return SSEShutdownManager(logger=logger, connection_metrics=connection_metrics)

    @provide(scope=Scope.REQUEST)
    def get_sse_service(
            self,
            sse_repository: SSERepository,
            router: SSEKafkaRedisBridge,
            sse_redis_bus: SSERedisBus,
            shutdown_manager: SSEShutdownManager,
            settings: Settings,
            logger: logging.Logger,
            connection_metrics: ConnectionMetrics,
    ) -> SSEService:
        return SSEService(
            repository=sse_repository,
            router=router,
            sse_bus=sse_redis_bus,
            shutdown_manager=shutdown_manager,
            settings=settings,
            logger=logger,
            connection_metrics=connection_metrics,
        )


class AuthProvider(Provider):
    scope = Scope.APP

    @provide
    def get_auth_service(
            self, user_repository: UserRepository, security_service: SecurityService, logger: logging.Logger
    ) -> AuthService:
        return AuthService(user_repository, security_service, logger)


class KafkaServicesProvider(Provider):
    """Provides Kafka-related event services used by both main app and workers."""

    scope = Scope.APP

    @provide
    def get_event_service(self, event_repository: EventRepository) -> EventService:
        return EventService(event_repository)

    @provide
    def get_kafka_event_service(
            self,
            event_repository: EventRepository,
            kafka_producer: UnifiedProducer,
            settings: Settings,
            logger: logging.Logger,
            event_metrics: EventMetrics,
    ) -> KafkaEventService:
        return KafkaEventService(
            event_repository=event_repository,
            kafka_producer=kafka_producer,
            settings=settings,
            logger=logger,
            event_metrics=event_metrics,
        )


class UserServicesProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_user_settings_service(
            self,
            repository: UserSettingsRepository,
            kafka_event_service: KafkaEventService,
            event_bus: EventBus,
            logger: logging.Logger,
    ) -> UserSettingsService:
        service = UserSettingsService(repository, kafka_event_service, event_bus, logger)
        await service.setup_event_subscription()
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
            event_bus: EventBus,
            sse_redis_bus: SSERedisBus,
            settings: Settings,
            logger: logging.Logger,
            notification_metrics: NotificationMetrics,
    ) -> NotificationService:
        return NotificationService(
            notification_repository=notification_repository,
            event_bus=event_bus,
            sse_bus=sse_redis_bus,
            settings=settings,
            logger=logger,
            notification_metrics=notification_metrics,
        )

    @provide
    def get_grafana_alert_processor(
            self,
            notification_service: NotificationService,
            logger: logging.Logger,
    ) -> GrafanaAlertProcessor:
        return GrafanaAlertProcessor(notification_service, logger)


def _create_default_saga_config() -> SagaConfig:
    """Factory for default SagaConfig used by orchestrators.

    Note: publish_commands=False because the coordinator worker handles
    publishing CreatePodCommand events. The saga orchestrator tracks state
    and handles completion events without duplicating command publishing.
    """
    return SagaConfig(
        name="main-orchestrator",
        timeout_seconds=300,
        max_retries=3,
        retry_delay_seconds=5,
        enable_compensation=True,
        store_events=True,
        publish_commands=False,
    )


class CoordinatorProvider(Provider):
    scope = Scope.APP

    @provide
    def get_execution_coordinator(
            self,
            kafka_producer: UnifiedProducer,
            execution_repository: ExecutionRepository,
            state_repo: ExecutionStateRepository,
            queue_repo: ExecutionQueueRepository,
            resource_repo: ResourceRepository,
            logger: logging.Logger,
            coordinator_metrics: CoordinatorMetrics,
            event_metrics: EventMetrics,
    ) -> ExecutionCoordinator:
        return ExecutionCoordinator(
            producer=kafka_producer,
            execution_repository=execution_repository,
            state_repo=state_repo,
            queue_repo=queue_repo,
            resource_repo=resource_repo,
            logger=logger,
            coordinator_metrics=coordinator_metrics,
            event_metrics=event_metrics,
        )


class K8sWorkerProvider(Provider):
    scope = Scope.APP

    @provide
    def get_kubernetes_worker(
            self,
            kafka_producer: UnifiedProducer,
            pod_state_repo: PodStateRepository,
            k8s_clients: K8sClients,
            logger: logging.Logger,
            kubernetes_metrics: KubernetesMetrics,
            execution_metrics: ExecutionMetrics,
            event_metrics: EventMetrics,
    ) -> KubernetesWorker:
        config = K8sWorkerConfig()
        return KubernetesWorker(
            config=config,
            producer=kafka_producer,
            pod_state_repo=pod_state_repo,
            v1_client=k8s_clients.v1,
            networking_v1_client=k8s_clients.networking_v1,
            apps_v1_client=k8s_clients.apps_v1,
            logger=logger,
            kubernetes_metrics=kubernetes_metrics,
            execution_metrics=execution_metrics,
            event_metrics=event_metrics,
        )


class PodMonitorProvider(Provider):
    scope = Scope.APP

    @provide
    def get_event_mapper(
            self,
            logger: logging.Logger,
            k8s_clients: K8sClients,
    ) -> PodEventMapper:
        return PodEventMapper(logger=logger, k8s_api=k8s_clients.v1)

    @provide
    def get_pod_monitor(
            self,
            kafka_producer: UnifiedProducer,
            pod_state_repo: PodStateRepository,
            k8s_clients: K8sClients,
            logger: logging.Logger,
            event_mapper: PodEventMapper,
            kubernetes_metrics: KubernetesMetrics,
    ) -> PodMonitor:
        config = PodMonitorConfig()
        return PodMonitor(
            config=config,
            producer=kafka_producer,
            pod_state_repo=pod_state_repo,
            v1_client=k8s_clients.v1,
            event_mapper=event_mapper,
            logger=logger,
            kubernetes_metrics=kubernetes_metrics,
        )


class SagaOrchestratorProvider(Provider):
    scope = Scope.APP

    @provide
    def get_saga_orchestrator(
            self,
            saga_repository: SagaRepository,
            kafka_producer: UnifiedProducer,
            resource_allocation_repository: ResourceAllocationRepository,
            logger: logging.Logger,
            event_metrics: EventMetrics,
    ) -> SagaOrchestrator:
        return SagaOrchestrator(
            config=_create_default_saga_config(),
            saga_repository=saga_repository,
            producer=kafka_producer,
            resource_allocation_repository=resource_allocation_repository,
            logger=logger,
            event_metrics=event_metrics,
        )


class BusinessServicesProvider(Provider):
    scope = Scope.REQUEST

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
            execution_metrics: ExecutionMetrics,
    ) -> ExecutionService:
        return ExecutionService(
            execution_repo=execution_repository,
            producer=kafka_producer,
            event_store=event_store,
            settings=settings,
            logger=logger,
            execution_metrics=execution_metrics,
        )

    @provide
    def get_saved_script_service(
            self, saved_script_repository: SavedScriptRepository, logger: logging.Logger
    ) -> SavedScriptService:
        return SavedScriptService(saved_script_repository, logger)

    @provide
    def get_replay_service(
            self,
            replay_repository: ReplayRepository,
            event_replay_service: EventReplayService,
            logger: logging.Logger,
    ) -> ReplayService:
        return ReplayService(replay_repository, event_replay_service, logger)

    @provide
    def get_admin_user_service(
            self,
            admin_user_repository: AdminUserRepository,
            event_service: EventService,
            execution_service: ExecutionService,
            rate_limit_service: RateLimitService,
            security_service: SecurityService,
            logger: logging.Logger,
    ) -> AdminUserService:
        return AdminUserService(
            user_repository=admin_user_repository,
            event_service=event_service,
            execution_service=execution_service,
            rate_limit_service=rate_limit_service,
            security_service=security_service,
            logger=logger,
        )


class EventReplayProvider(Provider):
    scope = Scope.APP

    @provide
    def get_event_replay_service(
            self,
            replay_repository: ReplayRepository,
            kafka_producer: UnifiedProducer,
            event_store: EventStore,
            settings: Settings,
            logger: logging.Logger,
    ) -> EventReplayService:
        return EventReplayService(
            repository=replay_repository,
            producer=kafka_producer,
            event_store=event_store,
            settings=settings,
            logger=logger,
        )
