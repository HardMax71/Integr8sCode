import logging
from collections.abc import AsyncIterable

import redis.asyncio as redis
from aiokafka import AIOKafkaProducer
from dishka import Provider, Scope, from_context, provide
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes import watch as k8s_watch

from app.core.logging import setup_logger
from app.core.metrics import (
    ConnectionMetrics,
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
from app.db.repositories.replay_repository import ReplayRepository
from app.db.repositories.resource_allocation_repository import ResourceAllocationRepository
from app.db.repositories.user_settings_repository import UserSettingsRepository
from app.dlq.manager import DLQManager
from app.dlq.models import RetryPolicy, RetryStrategy
from app.domain.enums.kafka import KafkaTopic
from app.domain.saga.models import SagaConfig
from app.events.core import ProducerMetrics, UnifiedProducer
from app.events.event_store import EventStore, create_event_store
from app.events.event_store_consumer import EventStoreService
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.admin import AdminEventsService, AdminSettingsService, AdminUserService
from app.services.auth_service import AuthService
from app.services.event_replay.replay_service import EventReplayService
from app.services.event_service import EventService
from app.services.execution_service import ExecutionService
from app.services.grafana_alert_processor import GrafanaAlertProcessor
from app.services.idempotency import IdempotencyConfig, IdempotencyManager
from app.services.idempotency.redis_repository import RedisIdempotencyRepository
from app.services.k8s_worker.config import K8sWorkerConfig
from app.services.k8s_worker.worker_logic import K8sWorkerLogic
from app.services.kafka_event_service import KafkaEventService
from app.services.notification_service import NotificationService
from app.services.pod_monitor.config import PodMonitorConfig
from app.services.pod_monitor.event_mapper import PodEventMapper
from app.services.pod_monitor.monitor import PodMonitor
from app.services.rate_limit_service import RateLimitService
from app.services.replay_service import ReplayService
from app.services.result_processor.processor_logic import ProcessorLogic
from app.services.saga.saga_logic import SagaLogic
from app.services.saga.saga_service import SagaService
from app.services.saved_script_service import SavedScriptService
from app.services.sse.redis_bus import SSERedisBus
from app.services.sse.sse_connection_registry import SSEConnectionRegistry
from app.services.sse.sse_service import SSEService
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


class BoundaryClientProvider(Provider):
    """Provides all external boundary clients (Redis, Kafka, K8s).

    These are the ONLY places that create connections to external systems.
    Override this provider in tests with fakes to test without external deps.
    """

    scope = Scope.APP

    # Redis
    @provide
    def get_redis_client(self, settings: Settings, logger: logging.Logger) -> redis.Redis:
        logger.info(f"Redis configured: {settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}")
        return redis.Redis(
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

    # Kafka - one shared producer for all services
    @provide
    async def get_kafka_producer_client(
            self, settings: Settings, logger: logging.Logger
    ) -> AsyncIterable[AIOKafkaProducer]:
        """Provide AIOKafkaProducer with DI-managed lifecycle."""
        producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            client_id=f"{settings.SERVICE_NAME}-producer",
            acks="all",
            compression_type="gzip",
            max_batch_size=16384,
            linger_ms=10,
            enable_idempotence=True,
        )
        await producer.start()
        logger.info("Kafka producer started")

        yield producer

        await producer.stop()
        logger.info("Kafka producer stopped")

    # Kubernetes
    @provide
    def get_k8s_api_client(self, settings: Settings, logger: logging.Logger) -> k8s_client.ApiClient:
        k8s_config.load_kube_config(config_file=settings.KUBERNETES_CONFIG_PATH)
        configuration = k8s_client.Configuration.get_default_copy()
        logger.info(f"Kubernetes API host: {configuration.host}")
        return k8s_client.ApiClient(configuration)

    @provide
    def get_k8s_core_v1_api(self, api_client: k8s_client.ApiClient) -> k8s_client.CoreV1Api:
        return k8s_client.CoreV1Api(api_client)

    @provide
    def get_k8s_apps_v1_api(self, api_client: k8s_client.ApiClient) -> k8s_client.AppsV1Api:
        return k8s_client.AppsV1Api(api_client)

    @provide
    def get_k8s_watch(self) -> k8s_watch.Watch:
        return k8s_watch.Watch()


class RedisServicesProvider(Provider):
    """Services that depend on Redis."""

    scope = Scope.APP

    @provide
    def get_rate_limit_service(
            self, redis_client: redis.Redis, settings: Settings, rate_limit_metrics: RateLimitMetrics
    ) -> RateLimitService:
        return RateLimitService(redis_client, settings, rate_limit_metrics)


class CoreServicesProvider(Provider):
    scope = Scope.APP

    @provide
    def get_security_service(self, settings: Settings) -> SecurityService:
        return SecurityService(settings)

    @provide
    def get_tracer_manager(self, settings: Settings) -> TracerManager:
        return TracerManager(tracer_name=settings.TRACING_SERVICE_NAME)


class MessagingProvider(Provider):
    scope = Scope.APP

    @provide
    def get_kafka_producer(
            self,
            kafka_producer: AIOKafkaProducer,
            schema_registry: SchemaRegistryManager,
            settings: Settings,
            logger: logging.Logger,
            event_metrics: EventMetrics,
    ) -> UnifiedProducer:
        """Provide UnifiedProducer. Kafka producer lifecycle managed by BoundaryClientProvider."""
        return UnifiedProducer(
            producer=kafka_producer,
            metrics=ProducerMetrics(),
            schema_registry=schema_registry,
            settings=settings,
            logger=logger,
            event_metrics=event_metrics,
        )

    @provide
    def get_dlq_manager(
            self,
            kafka_producer: AIOKafkaProducer,
            settings: Settings,
            schema_registry: SchemaRegistryManager,
            logger: logging.Logger,
            dlq_metrics: DLQMetrics,
    ) -> DLQManager:
        """Provide DLQManager instance.

        Message consumption handled by FastStream subscriber in dlq_processor worker.
        Scheduled retries handled by timer in worker lifespan.
        Producer lifecycle managed by BoundaryClientProvider.
        """
        return DLQManager(
            settings=settings,
            producer=kafka_producer,
            schema_registry=schema_registry,
            logger=logger,
            dlq_metrics=dlq_metrics,
            dlq_topic=KafkaTopic.DEAD_LETTER_QUEUE,
            default_retry_policy=RetryPolicy(topic="default", strategy=RetryStrategy.EXPONENTIAL_BACKOFF),
        )

    @provide
    def get_idempotency_config(self) -> IdempotencyConfig:
        return IdempotencyConfig()

    @provide
    def get_idempotency_repository(self, redis_client: redis.Redis) -> RedisIdempotencyRepository:
        return RedisIdempotencyRepository(redis_client, key_prefix="idempotency")

    @provide
    def get_idempotency_manager(
            self,
            repository: RedisIdempotencyRepository,
            logger: logging.Logger,
            metrics: DatabaseMetrics,
            config: IdempotencyConfig,
    ) -> IdempotencyManager:
        return IdempotencyManager(
            repository=repository,
            logger=logger,
            metrics=metrics,
            config=config,
        )


class EventProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_schema_registry(
        self, settings: Settings, logger: logging.Logger
    ) -> AsyncIterable[SchemaRegistryManager]:
        """Provide SchemaRegistryManager with DI-managed initialization."""
        registry = SchemaRegistryManager(settings, logger)
        await registry.initialize_schemas()
        logger.info("Schema registry initialized")
        yield registry

    @provide
    def get_event_store(
            self, schema_registry: SchemaRegistryManager, logger: logging.Logger, event_metrics: EventMetrics
    ) -> EventStore:
        return create_event_store(
            schema_registry=schema_registry, logger=logger, event_metrics=event_metrics, ttl_days=90
        )

    @provide
    def get_event_store_service(
            self,
            event_store: EventStore,
            logger: logging.Logger,
            event_metrics: EventMetrics,
    ) -> EventStoreService:
        """Provide EventStoreService for event archival.

        Pure storage service - no consumer, no loops.
        FastStream subscribers call store_event() to archive events.
        """
        return EventStoreService(
            event_store=event_store,
            logger=logger,
            event_metrics=event_metrics,
        )

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
    """Provides SSE (Server-Sent Events) related services.

    Note: Kafka consumers for SSE are now in the separate SSE bridge worker
    (run_sse_bridge.py). This provider only handles Redis pub/sub and SSE service.
    """

    scope = Scope.APP

    @provide
    def get_sse_redis_bus(self, redis_client: redis.Redis, logger: logging.Logger) -> SSERedisBus:
        return SSERedisBus(redis_client, logger)

    @provide(scope=Scope.REQUEST)
    def get_sse_connection_registry(
            self,
            logger: logging.Logger,
            connection_metrics: ConnectionMetrics,
    ) -> SSEConnectionRegistry:
        return SSEConnectionRegistry(
            logger=logger,
            connection_metrics=connection_metrics,
        )

    @provide(scope=Scope.REQUEST)
    def get_sse_service(
            self,
            sse_repository: SSERepository,
            sse_redis_bus: SSERedisBus,
            connection_registry: SSEConnectionRegistry,
            settings: Settings,
            logger: logging.Logger,
            connection_metrics: ConnectionMetrics,
    ) -> SSEService:
        return SSEService(
            repository=sse_repository,
            sse_bus=sse_redis_bus,
            connection_registry=connection_registry,
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
    def get_user_settings_service(
            self,
            repository: UserSettingsRepository,
            kafka_event_service: KafkaEventService,
            redis_client: redis.Redis,
            logger: logging.Logger,
    ) -> UserSettingsService:
        """Provide UserSettingsService with Redis-backed cache.

        No pub/sub subscription needed - Redis cache is shared across all instances.
        """
        return UserSettingsService(repository, kafka_event_service, logger, redis_client)


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
            sse_redis_bus: SSERedisBus,
            settings: Settings,
            logger: logging.Logger,
            notification_metrics: NotificationMetrics,
    ) -> NotificationService:
        """Provide NotificationService instance.

        Background tasks (pending batch processing, cleanup) managed by app lifespan.
        """
        return NotificationService(
            notification_repository=notification_repository,
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


class BusinessServicesProvider(Provider):
    scope = Scope.REQUEST

    @provide
    def get_saga_service(
            self,
            saga_repository: SagaRepository,
            execution_repository: ExecutionRepository,
            saga_logic: SagaLogic,
            logger: logging.Logger,
    ) -> SagaService:
        return SagaService(
            saga_repo=saga_repository,
            execution_repo=execution_repository,
            saga_logic=saga_logic,
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
            kafka_producer: UnifiedProducer,
            event_store: EventStore,
            settings: Settings,
            logger: logging.Logger,
    ) -> ReplayService:
        event_replay_service = EventReplayService(
            repository=replay_repository,
            producer=kafka_producer,
            event_store=event_store,
            settings=settings,
            logger=logger,
        )
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


class K8sWorkerProvider(Provider):
    scope = Scope.APP

    @provide
    def get_k8s_worker_logic(
            self,
            kafka_producer: UnifiedProducer,
            settings: Settings,
            logger: logging.Logger,
            event_metrics: EventMetrics,
            kubernetes_metrics: KubernetesMetrics,
            execution_metrics: ExecutionMetrics,
            k8s_v1: k8s_client.CoreV1Api,
            k8s_apps_v1: k8s_client.AppsV1Api,
    ) -> K8sWorkerLogic:
        config = K8sWorkerConfig()
        return K8sWorkerLogic(
            config=config,
            producer=kafka_producer,
            settings=settings,
            logger=logger,
            event_metrics=event_metrics,
            kubernetes_metrics=kubernetes_metrics,
            execution_metrics=execution_metrics,
            k8s_v1=k8s_v1,
            k8s_apps_v1=k8s_apps_v1,
        )


class PodMonitorProvider(Provider):
    scope = Scope.APP

    @provide
    def get_event_mapper(
            self,
            logger: logging.Logger,
            k8s_v1: k8s_client.CoreV1Api,
    ) -> PodEventMapper:
        return PodEventMapper(logger=logger, k8s_api=k8s_v1)

    @provide
    def get_pod_monitor(
            self,
            kafka_event_service: KafkaEventService,
            k8s_v1: k8s_client.CoreV1Api,
            k8s_watch: k8s_watch.Watch,
            logger: logging.Logger,
            event_mapper: PodEventMapper,
            kubernetes_metrics: KubernetesMetrics,
    ) -> PodMonitor:
        config = PodMonitorConfig()
        return PodMonitor(
            config=config,
            kafka_event_service=kafka_event_service,
            logger=logger,
            k8s_v1=k8s_v1,
            k8s_watch=k8s_watch,
            event_mapper=event_mapper,
            kubernetes_metrics=kubernetes_metrics,
        )


class SagaOrchestratorProvider(Provider):
    scope = Scope.APP

    @provide
    def get_saga_logic(
            self,
            saga_repository: SagaRepository,
            kafka_producer: UnifiedProducer,
            resource_allocation_repository: ResourceAllocationRepository,
            logger: logging.Logger,
            event_metrics: EventMetrics,
    ) -> SagaLogic:
        logic = SagaLogic(
            config=_create_default_saga_config(),
            saga_repository=saga_repository,
            producer=kafka_producer,
            resource_allocation_repository=resource_allocation_repository,
            logger=logger,
            event_metrics=event_metrics,
        )
        # Register default sagas
        logic.register_default_sagas()
        return logic


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


class ResultProcessorProvider(Provider):
    scope = Scope.APP

    @provide
    def get_processor_logic(
            self,
            execution_repo: ExecutionRepository,
            kafka_producer: UnifiedProducer,
            settings: Settings,
            logger: logging.Logger,
            execution_metrics: ExecutionMetrics,
    ) -> ProcessorLogic:
        return ProcessorLogic(
            execution_repo=execution_repo,
            producer=kafka_producer,
            settings=settings,
            logger=logger,
            execution_metrics=execution_metrics,
        )
