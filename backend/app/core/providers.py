from typing import AsyncIterator

import redis.asyncio as redis
from dishka import Provider, Scope, provide
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database_context import (
    AsyncDatabaseConnection,
    DatabaseConfig,
    create_database_connection,
)
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
from app.services.idempotency import IdempotencyConfig, IdempotencyManager
from app.services.idempotency.idempotency_manager import create_idempotency_manager
from app.services.idempotency.redis_repository import RedisIdempotencyRepository
from app.services.kafka_event_service import KafkaEventService
from app.services.notification_service import NotificationService
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
from app.settings import Settings, get_settings


class SettingsProvider(Provider):
    scope = Scope.APP

    @provide
    def get_settings(self) -> Settings:
        return get_settings()


class DatabaseProvider(Provider):
    scope = Scope.APP

    @provide(scope=Scope.APP)
    async def get_database_connection(self, settings: Settings) -> AsyncIterator[AsyncDatabaseConnection]:
        db_config = DatabaseConfig(
            mongodb_url=settings.MONGODB_URL,
            db_name=settings.PROJECT_NAME + "_test" if settings.TESTING else settings.PROJECT_NAME,
            server_selection_timeout_ms=5000,
            connect_timeout_ms=5000,
            max_pool_size=50,
            min_pool_size=10
        )

        db_connection = create_database_connection(db_config)
        await db_connection.connect()
        try:
            yield db_connection
        finally:
            await db_connection.disconnect()

    @provide
    def get_database(self, db_connection: AsyncDatabaseConnection) -> AsyncIOMotorDatabase:
        return db_connection.database


class RedisProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_redis_client(self, settings: Settings) -> AsyncIterator[redis.Redis]:
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
        await client.ping()
        try:
            yield client
        finally:
            await client.aclose()

    @provide
    def get_rate_limit_service(
            self,
            redis_client: redis.Redis,
            settings: Settings,
            rate_limit_metrics: RateLimitMetrics
    ) -> RateLimitService:
        return RateLimitService(redis_client, settings, rate_limit_metrics)


class CoreServicesProvider(Provider):
    scope = Scope.APP

    @provide
    def get_tracer_manager(self, settings: Settings) -> TracerManager:
        return TracerManager(tracer_name=settings.TRACING_SERVICE_NAME)


class MessagingProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_kafka_producer(
            self,
            settings: Settings,
            schema_registry: SchemaRegistryManager
    ) -> AsyncIterator[UnifiedProducer]:
        config = ProducerConfig(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS
        )
        producer = UnifiedProducer(config, schema_registry)
        await producer.start()
        try:
            yield producer
        finally:
            await producer.stop()

    @provide
    async def get_dlq_manager(self, database: AsyncIOMotorDatabase) -> AsyncIterator[DLQManager]:
        manager = create_dlq_manager(database)
        await manager.start()
        try:
            yield manager
        finally:
            await manager.stop()

    @provide
    def get_idempotency_repository(self,
                                   redis_client: redis.Redis) -> RedisIdempotencyRepository:
        return RedisIdempotencyRepository(redis_client,
                                          key_prefix="idempotency")

    @provide
    async def get_idempotency_manager(self,
                                      repo: RedisIdempotencyRepository) -> AsyncIterator[IdempotencyManager]:
        manager = create_idempotency_manager(repository=repo,
                                             config=IdempotencyConfig())
        await manager.initialize()
        try:
            yield manager
        finally:
            await manager.close()


class EventProvider(Provider):
    scope = Scope.APP

    @provide
    def get_schema_registry(self) -> SchemaRegistryManager:
        return create_schema_registry_manager()

    @provide
    async def get_event_store(
            self,
            database: AsyncIOMotorDatabase,
            schema_registry: SchemaRegistryManager
    ) -> EventStore:
        store = create_event_store(
            db=database,
            schema_registry=schema_registry,
            ttl_days=90
        )
        return store

    @provide
    async def get_event_store_consumer(
            self,
            event_store: EventStore,
            schema_registry: SchemaRegistryManager,
            kafka_producer: UnifiedProducer
    ) -> AsyncIterator[EventStoreConsumer]:
        topics = get_all_topics()
        consumer = create_event_store_consumer(
            event_store=event_store,
            topics=list(topics),
            schema_registry_manager=schema_registry,
            producer=kafka_producer
        )
        await consumer.start()
        try:
            yield consumer
        finally:
            await consumer.stop()

    @provide
    def get_event_bus_manager(self) -> EventBusManager:
        # Don't start the event bus here - let it start lazily when needed
        return EventBusManager()


class ConnectionProvider(Provider):
    scope = Scope.APP

    @provide
    def get_event_metrics(self) -> EventMetrics:
        # Create the metrics instance that will be placed in context
        # No longer a singleton - context manages the single instance
        return EventMetrics()

    @provide
    def get_connection_metrics(self) -> ConnectionMetrics:
        # Create the metrics instance that will be placed in context
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

    @provide(scope=Scope.REQUEST)
    def get_sse_shutdown_manager(self) -> SSEShutdownManager:
        return create_sse_shutdown_manager()

    @provide(scope=Scope.APP)
    async def get_sse_kafka_redis_bridge(
            self,
            schema_registry: SchemaRegistryManager,
            settings: Settings,
            event_metrics: EventMetrics,
            sse_redis_bus: SSERedisBus,
    ) -> AsyncIterator[SSEKafkaRedisBridge]:
        router = create_sse_kafka_redis_bridge(
            schema_registry=schema_registry,
            settings=settings,
            event_metrics=event_metrics,
            sse_bus=sse_redis_bus,
        )
        await router.start()
        try:
            yield router
        finally:
            await router.stop()

    @provide
    def get_sse_repository(
            self,
            database: AsyncIOMotorDatabase
    ) -> SSERepository:
        return SSERepository(database)

    @provide
    async def get_sse_redis_bus(self, redis_client: redis.Redis) -> AsyncIterator[SSERedisBus]:
        bus = SSERedisBus(redis_client)
        yield bus

    @provide(scope=Scope.REQUEST)
    def get_sse_service(
            self,
            sse_repository: SSERepository,
            router: SSEKafkaRedisBridge,
            sse_redis_bus: SSERedisBus,
            shutdown_manager: SSEShutdownManager,
            settings: Settings
    ) -> SSEService:
        # Ensure shutdown manager coordinates with the router in this request scope
        shutdown_manager.set_router(router)
        return SSEService(
            repository=sse_repository,
            router=router,
            sse_bus=sse_redis_bus,
            shutdown_manager=shutdown_manager,
            settings=settings
        )


class AuthProvider(Provider):
    scope = Scope.APP

    @provide
    def get_user_repository(self, database: AsyncIOMotorDatabase) -> UserRepository:
        return UserRepository(database)

    @provide
    def get_auth_service(self, user_repository: UserRepository) -> AuthService:
        return AuthService(user_repository)


class UserServicesProvider(Provider):
    scope = Scope.APP

    @provide
    def get_user_settings_repository(self, database: AsyncIOMotorDatabase) -> UserSettingsRepository:
        return UserSettingsRepository(database)

    @provide
    def get_event_repository(self, database: AsyncIOMotorDatabase) -> EventRepository:
        return EventRepository(database)

    @provide
    async def get_event_service(self, event_repository: EventRepository) -> EventService:
        return EventService(event_repository)

    @provide
    async def get_kafka_event_service(
            self,
            event_repository: EventRepository,
            kafka_producer: UnifiedProducer
    ) -> KafkaEventService:
        return KafkaEventService(
            event_repository=event_repository,
            kafka_producer=kafka_producer
        )

    @provide
    async def get_user_settings_service(
            self,
            repository: UserSettingsRepository,
            kafka_event_service: KafkaEventService,
            event_bus_manager: EventBusManager
    ) -> UserSettingsService:
        service = UserSettingsService(repository, kafka_event_service)
        await service.initialize(event_bus_manager)
        return service


class AdminServicesProvider(Provider):
    scope = Scope.APP

    @provide
    def get_admin_events_repository(self, database: AsyncIOMotorDatabase) -> AdminEventsRepository:
        return AdminEventsRepository(database)

    @provide(scope=Scope.REQUEST)
    def get_admin_events_service(
            self,
            admin_events_repository: AdminEventsRepository,
            replay_service: ReplayService,
    ) -> AdminEventsService:
        return AdminEventsService(admin_events_repository, replay_service)

    @provide
    def get_admin_settings_repository(self, database: AsyncIOMotorDatabase) -> AdminSettingsRepository:
        return AdminSettingsRepository(database)

    @provide
    def get_admin_settings_service(
            self,
            admin_settings_repository: AdminSettingsRepository,
    ) -> AdminSettingsService:
        return AdminSettingsService(admin_settings_repository)

    @provide
    def get_admin_user_repository(self, database: AsyncIOMotorDatabase) -> AdminUserRepository:
        return AdminUserRepository(database)

    @provide
    def get_saga_repository(self, database: AsyncIOMotorDatabase) -> SagaRepository:
        return SagaRepository(database)

    @provide
    def get_notification_repository(self, database: AsyncIOMotorDatabase) -> NotificationRepository:
        return NotificationRepository(database)

    @provide
    async def get_notification_service(
            self,
            notification_repository: NotificationRepository,
            kafka_event_service: KafkaEventService,
            event_bus_manager: EventBusManager,
            schema_registry: SchemaRegistryManager,
            sse_redis_bus: SSERedisBus,
            settings: Settings,
    ) -> NotificationService:
        service = NotificationService(
            notification_repository=notification_repository,
            event_service=kafka_event_service,
            event_bus_manager=event_bus_manager,
            schema_registry_manager=schema_registry,
            sse_bus=sse_redis_bus,
            settings=settings,
        )
        await service.initialize()
        return service


class BusinessServicesProvider(Provider):
    scope = Scope.REQUEST

    @provide
    def get_execution_repository(self, database: AsyncIOMotorDatabase) -> ExecutionRepository:
        return ExecutionRepository(database)

    @provide
    def get_resource_allocation_repository(self, database: AsyncIOMotorDatabase) -> ResourceAllocationRepository:
        return ResourceAllocationRepository(database)

    @provide
    def get_saved_script_repository(self, database: AsyncIOMotorDatabase) -> SavedScriptRepository:
        return SavedScriptRepository(database)

    @provide
    def get_dlq_repository(self, database: AsyncIOMotorDatabase) -> DLQRepository:
        return DLQRepository(database)

    @provide
    def get_replay_repository(self, database: AsyncIOMotorDatabase) -> ReplayRepository:
        return ReplayRepository(database)

    @provide
    async def get_saga_orchestrator(
            self,
            saga_repository: SagaRepository,
            kafka_producer: UnifiedProducer,
            event_store: EventStore,
            idempotency_manager: IdempotencyManager,
            resource_allocation_repository: ResourceAllocationRepository,
            settings: Settings,
    ) -> AsyncIterator[SagaOrchestrator]:
        config = SagaConfig(
            name="main-orchestrator",
            timeout_seconds=300,
            max_retries=3,
            retry_delay_seconds=5,
            enable_compensation=True,
            store_events=True,
            publish_commands=True,
        )
        orchestrator = create_saga_orchestrator(
            saga_repository=saga_repository,
            producer=kafka_producer,
            event_store=event_store,
            idempotency_manager=idempotency_manager,
            resource_allocation_repository=resource_allocation_repository,
            config=config,
        )
        try:
            yield orchestrator
        finally:
            await orchestrator.stop()

    @provide
    def get_saga_service(
            self,
            saga_repository: SagaRepository,
            execution_repository: ExecutionRepository,
            saga_orchestrator: SagaOrchestrator
    ) -> SagaService:
        return SagaService(
            saga_repo=saga_repository,
            execution_repo=execution_repository,
            orchestrator=saga_orchestrator
        )

    @provide
    def get_execution_service(
            self,
            execution_repository: ExecutionRepository,
            kafka_producer: UnifiedProducer,
            event_store: EventStore,
            settings: Settings
    ) -> ExecutionService:
        return ExecutionService(
            execution_repo=execution_repository,
            producer=kafka_producer,
            event_store=event_store,
            settings=settings
        )

    @provide
    def get_saved_script_service(
            self,
            saved_script_repository: SavedScriptRepository
    ) -> SavedScriptService:
        return SavedScriptService(saved_script_repository)

    @provide
    async def get_replay_service(
            self,
            replay_repository: ReplayRepository,
            kafka_producer: UnifiedProducer,
            event_store: EventStore
    ) -> ReplayService:
        event_replay_service = EventReplayService(
            repository=replay_repository,
            producer=kafka_producer,
            event_store=event_store
        )
        return ReplayService(replay_repository, event_replay_service)

    @provide
    def get_admin_user_service(
            self,
            admin_user_repository: AdminUserRepository,
            event_service: EventService,
            execution_service: ExecutionService,
            rate_limit_service: RateLimitService,
    ) -> AdminUserService:
        return AdminUserService(
            user_repository=admin_user_repository,
            event_service=event_service,
            execution_service=execution_service,
            rate_limit_service=rate_limit_service,
        )

    @provide
    async def get_execution_coordinator(
            self,
            kafka_producer: UnifiedProducer,
            schema_registry: SchemaRegistryManager,
            event_store: EventStore,
            execution_repository: ExecutionRepository,
            idempotency_manager: IdempotencyManager,
    ) -> AsyncIterator[ExecutionCoordinator]:
        coordinator = ExecutionCoordinator(
            producer=kafka_producer,
            schema_registry_manager=schema_registry,
            event_store=event_store,
            execution_repository=execution_repository,
            idempotency_manager=idempotency_manager,
        )
        try:
            yield coordinator
        finally:
            await coordinator.stop()


class ResultProcessorProvider(Provider):
    scope = Scope.APP

    @provide
    def get_execution_repository(self, database: AsyncIOMotorDatabase) -> ExecutionRepository:
        return ExecutionRepository(database)
