import logging
from typing import AsyncIterator

import redis.asyncio as redis
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from dishka import Provider, Scope, from_context, provide
from pymongo.asynchronous.mongo_client import AsyncMongoClient

from app.core.database_context import Database
from app.core.k8s_clients import K8sClients, close_k8s_clients, create_k8s_clients
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
from app.domain.enums.kafka import CONSUMER_GROUP_SUBSCRIPTIONS, GroupId, KafkaTopic
from app.domain.saga.models import SagaConfig
from app.events.core import ConsumerConfig, EventDispatcher, UnifiedConsumer, UnifiedProducer
from app.events.event_store import EventStore, create_event_store
from app.events.event_store_consumer import EventStoreConsumer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.topics import get_all_topics
from app.services.admin import AdminEventsService, AdminSettingsService, AdminUserService
from app.services.auth_service import AuthService
from app.services.event_bus import EventBus, EventBusEvent
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
from app.services.sse.event_router import SSEEventRouter
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
    def get_security_service(self, settings: Settings) -> SecurityService:
        return SecurityService(settings)

    @provide
    def get_tracer_manager(self, settings: Settings) -> TracerManager:
        return TracerManager(tracer_name=settings.TRACING_SERVICE_NAME)


class MessagingProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_kafka_producer(
            self, settings: Settings, schema_registry: SchemaRegistryManager, logger: logging.Logger,
            event_metrics: EventMetrics
    ) -> AsyncIterator[UnifiedProducer]:
        async with UnifiedProducer(schema_registry, logger, settings, event_metrics) as producer:
            yield producer

    @provide
    async def get_dlq_manager(
            self,
            settings: Settings,
            schema_registry: SchemaRegistryManager,
            logger: logging.Logger,
            dlq_metrics: DLQMetrics,
    ) -> AsyncIterator[DLQManager]:
        topic_name = f"{settings.KAFKA_TOPIC_PREFIX}{KafkaTopic.DEAD_LETTER_QUEUE}"
        consumer = AIOKafkaConsumer(
            topic_name,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=f"{GroupId.DLQ_MANAGER}.{settings.KAFKA_GROUP_SUFFIX}",
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            client_id="dlq-manager-consumer",
            session_timeout_ms=settings.KAFKA_SESSION_TIMEOUT_MS,
            heartbeat_interval_ms=settings.KAFKA_HEARTBEAT_INTERVAL_MS,
            max_poll_interval_ms=settings.KAFKA_MAX_POLL_INTERVAL_MS,
            request_timeout_ms=settings.KAFKA_REQUEST_TIMEOUT_MS,
        )
        producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            client_id="dlq-manager-producer",
            acks="all",
            compression_type="gzip",
            max_batch_size=16384,
            linger_ms=10,
            enable_idempotence=True,
        )
        manager = DLQManager(
            settings=settings,
            consumer=consumer,
            producer=producer,
            schema_registry=schema_registry,
            logger=logger,
            dlq_metrics=dlq_metrics,
            dlq_topic=KafkaTopic.DEAD_LETTER_QUEUE,
            default_retry_policy=RetryPolicy(topic="default", strategy=RetryStrategy.EXPONENTIAL_BACKOFF),
        )
        async with manager:
            yield manager

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
    def get_schema_registry(self, settings: Settings, logger: logging.Logger) -> SchemaRegistryManager:
        return SchemaRegistryManager(settings, logger)

    @provide
    async def get_event_store(
            self, schema_registry: SchemaRegistryManager, logger: logging.Logger, event_metrics: EventMetrics
    ) -> EventStore:
        return create_event_store(
            schema_registry=schema_registry, logger=logger, event_metrics=event_metrics, ttl_days=90
        )

    @provide
    def get_event_store_consumer(
            self,
            event_store: EventStore,
            schema_registry: SchemaRegistryManager,
            settings: Settings,
            logger: logging.Logger,
            event_metrics: EventMetrics,
    ) -> EventStoreConsumer:
        topics = get_all_topics()
        return EventStoreConsumer(
            event_store=event_store,
            topics=list(topics),
            schema_registry_manager=schema_registry,
            settings=settings,
            logger=logger,
            event_metrics=event_metrics,
        )

    @provide
    async def get_event_bus(
            self, settings: Settings, logger: logging.Logger, connection_metrics: ConnectionMetrics
    ) -> AsyncIterator[EventBus]:
        async with EventBus(settings, logger, connection_metrics) as bus:
            yield bus


class KubernetesProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_k8s_clients(self, settings: Settings, logger: logging.Logger) -> AsyncIterator[K8sClients]:
        clients = create_k8s_clients(logger, kubeconfig_path=settings.KUBERNETES_CONFIG_PATH)
        try:
            yield clients
        finally:
            close_k8s_clients(clients)


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
    """Provides SSE (Server-Sent Events) related services."""

    scope = Scope.APP

    @provide
    async def get_sse_redis_bus(self, redis_client: redis.Redis, logger: logging.Logger) -> AsyncIterator[SSERedisBus]:
        bus = SSERedisBus(redis_client, logger)
        yield bus

    @provide
    def get_sse_event_router(
            self,
            sse_redis_bus: SSERedisBus,
            logger: logging.Logger,
    ) -> SSEEventRouter:
        return SSEEventRouter(sse_bus=sse_redis_bus, logger=logger)

    @provide
    def get_sse_consumers(
            self,
            router: SSEEventRouter,
            schema_registry: SchemaRegistryManager,
            settings: Settings,
            event_metrics: EventMetrics,
            logger: logging.Logger,
    ) -> list[UnifiedConsumer]:
        """Create SSE consumer pool with routing handlers wired to SSEEventRouter."""
        topics = list(CONSUMER_GROUP_SUBSCRIPTIONS[GroupId.WEBSOCKET_GATEWAY])
        suffix = settings.KAFKA_GROUP_SUFFIX
        consumers: list[UnifiedConsumer] = []

        for i in range(settings.SSE_CONSUMER_POOL_SIZE):
            dispatcher = EventDispatcher(logger=logger)
            router.register_handlers(dispatcher)

            config = ConsumerConfig(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                group_id=f"sse-bridge-pool.{suffix}",
                client_id=f"sse-bridge-{i}.{suffix}",
                enable_auto_commit=True,
                auto_offset_reset="latest",
                max_poll_interval_ms=settings.KAFKA_MAX_POLL_INTERVAL_MS,
                session_timeout_ms=settings.KAFKA_SESSION_TIMEOUT_MS,
                heartbeat_interval_ms=settings.KAFKA_HEARTBEAT_INTERVAL_MS,
                request_timeout_ms=settings.KAFKA_REQUEST_TIMEOUT_MS,
            )

            consumer = UnifiedConsumer(
                config=config,
                dispatcher=dispatcher,
                schema_registry=schema_registry,
                settings=settings,
                logger=logger,
                event_metrics=event_metrics,
                topics=topics,
            )
            consumers.append(consumer)

        return consumers

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
            consumers: list[UnifiedConsumer],
            sse_redis_bus: SSERedisBus,
            connection_registry: SSEConnectionRegistry,
            settings: Settings,
            logger: logging.Logger,
            connection_metrics: ConnectionMetrics,
    ) -> SSEService:
        return SSEService(
            repository=sse_repository,
            num_consumers=len(consumers),
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
    async def get_user_settings_service(
            self,
            repository: UserSettingsRepository,
            kafka_event_service: KafkaEventService,
            event_bus: EventBus,
            logger: logging.Logger,
    ) -> UserSettingsService:
        service = UserSettingsService(repository, kafka_event_service, logger, event_bus)

        # Subscribe to settings update events for cross-instance cache invalidation.
        # EventBus filters out self-published messages, so this handler only
        # runs for events from OTHER instances.
        async def _handle_settings_update(evt: EventBusEvent) -> None:
            uid = evt.payload.get("user_id")
            if uid:
                await service.invalidate_cache(str(uid))

        await event_bus.subscribe("user.settings.updated*", _handle_settings_update)

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


# Standalone factory functions for services (no lifecycle - run() handles everything)




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
    async def get_replay_service(
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
    ) -> K8sWorkerLogic:
        config = K8sWorkerConfig()
        logic = K8sWorkerLogic(
            config=config,
            producer=kafka_producer,
            settings=settings,
            logger=logger,
            event_metrics=event_metrics,
        )
        # Initialize K8s clients synchronously (safe during DI setup)
        logic.initialize()
        return logic


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
            kafka_event_service: KafkaEventService,
            k8s_clients: K8sClients,
            logger: logging.Logger,
            event_mapper: PodEventMapper,
            kubernetes_metrics: KubernetesMetrics,
    ) -> PodMonitor:
        config = PodMonitorConfig()
        return PodMonitor(
            config=config,
            kafka_event_service=kafka_event_service,
            logger=logger,
            k8s_clients=k8s_clients,
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
