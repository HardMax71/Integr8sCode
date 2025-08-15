import asyncio
from typing import Annotated

from fastapi import Depends, Request
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import get_settings
from app.core.database_context import DatabaseProvider, get_database_provider
from app.db.repositories import (
    EventRepository,
    ExecutionRepository,
    NotificationRepository,
    ProjectionRepository,
    SagaRepository,
    SavedScriptRepository,
    SSERepository,
    UserRepository,
    WebSocketRepository,
)
from app.db.repositories.admin.admin_events_repository import AdminEventsRepository
from app.db.repositories.admin.admin_settings_repository import AdminSettingsRepository
from app.db.repositories.admin.admin_user_repository import AdminUserRepository
from app.db.repositories.dlq_repository import DLQRepository
from app.db.repositories.health_dashboard_repository import HealthDashboardRepository
from app.db.repositories.kafka_metrics_repository import KafkaMetricsRepository
from app.db.repositories.replay_repository import ReplayRepository
from app.dlq.consumer import DLQConsumerRegistry
from app.dlq.manager import DLQManager
from app.events.core.producer import UnifiedProducer
from app.events.kafka.cb import KafkaCircuitBreakerManager
from app.events.kafka.metrics.metrics_service import KafkaMetricsService
from app.events.schema.schema_registry import SchemaRegistryManager
from app.events.store.event_store import EventStore, EventStoreConsumer
from app.services.event_bus import EventBus, EventBusManager
from app.services.event_projections import EventProjectionService
from app.services.event_replay.replay_service import EventReplayService
from app.services.execution_service import ExecutionService
from app.services.idempotency import IdempotencyManager
from app.services.kafka_event_service import KafkaEventService
from app.services.kubernetes_service import KubernetesService
from app.services.notification_service import NotificationService
from app.services.saga.saga_orchestrator import SagaConfig, SagaOrchestrator
from app.services.saved_script_service import SavedScriptService
from app.services.sse_connection_manager import SSEConnectionManager
from app.services.sse_shutdown_manager import SSEShutdownManager
from app.services.user_settings_service import UserSettingsService
from app.websocket.auth import WebSocketAuth
from app.websocket.connection_manager import ConnectionManager
from app.websocket.event_handler import WebSocketEventHandler


async def get_database(
        provider: Annotated[DatabaseProvider, Depends(get_database_provider)]
) -> AsyncIOMotorDatabase:
    return provider.database


async def get_event_repository(
        database: Annotated[AsyncIOMotorDatabase, Depends(get_database)]
) -> EventRepository:
    return EventRepository(database)


async def get_execution_repository(
        database: Annotated[AsyncIOMotorDatabase, Depends(get_database)]
) -> ExecutionRepository:
    return ExecutionRepository(database)


async def get_notification_repository(
        database: Annotated[AsyncIOMotorDatabase, Depends(get_database)]
) -> NotificationRepository:
    return NotificationRepository(database)


async def get_projection_service(
        database: Annotated[AsyncIOMotorDatabase, Depends(get_database)]
) -> EventProjectionService:
    service = EventProjectionService(database)
    await service.initialize()
    return service


async def get_projection_repository(
        database: Annotated[AsyncIOMotorDatabase, Depends(get_database)],
        projection_service: Annotated[EventProjectionService, Depends(get_projection_service)]
) -> ProjectionRepository:
    repo = ProjectionRepository(database)
    repo.set_projection_service(projection_service)
    return repo


async def get_saga_repository(
        database: Annotated[AsyncIOMotorDatabase, Depends(get_database)]
) -> SagaRepository:
    return SagaRepository(database)


async def get_saved_script_repository(
        database: Annotated[AsyncIOMotorDatabase, Depends(get_database)]
) -> SavedScriptRepository:
    return SavedScriptRepository(database)


async def get_sse_repository(
        database: Annotated[AsyncIOMotorDatabase, Depends(get_database)],
        request: Request
) -> SSERepository:
    # Check if connection manager is in lifespan context
    lifespan_context = getattr(request.app.state, 'lifespan_context', None)
    connection_manager = None
    if lifespan_context and lifespan_context.sse_connection_manager:
        connection_manager = lifespan_context.sse_connection_manager

    return SSERepository(database, connection_manager)


async def get_user_repository(
        database: Annotated[AsyncIOMotorDatabase, Depends(get_database)]
) -> UserRepository:
    return UserRepository(database)


async def get_dlq_repository(
        database: Annotated[AsyncIOMotorDatabase, Depends(get_database)]
) -> DLQRepository:
    return DLQRepository(database)


async def get_health_dashboard_repository(
        database: Annotated[AsyncIOMotorDatabase, Depends(get_database)]
) -> HealthDashboardRepository:
    return HealthDashboardRepository(database)


async def get_kafka_metrics_service(request: Request) -> KafkaMetricsService:
    # Check if kafka metrics service is in lifespan context
    lifespan_context = getattr(request.app.state, 'lifespan_context', None)
    if lifespan_context and lifespan_context.kafka_metrics_service:
        service = lifespan_context.kafka_metrics_service
        if not isinstance(service, KafkaMetricsService):
            raise RuntimeError("Invalid kafka metrics service type")
        return service

    # Otherwise create a new one (for testing or standalone use)
    service = KafkaMetricsService()
    await service.initialize()
    return service


async def get_kafka_metrics_repository(
        database: Annotated[AsyncIOMotorDatabase, Depends(get_database)],
        kafka_metrics_service: Annotated[KafkaMetricsService, Depends(get_kafka_metrics_service)]
) -> KafkaMetricsRepository:
    return KafkaMetricsRepository(database, kafka_metrics_service)


async def get_circuit_breaker_manager(request: Request) -> KafkaCircuitBreakerManager:
    # Check if circuit breaker manager is in lifespan context
    lifespan_context = getattr(request.app.state, 'lifespan_context', None)
    if lifespan_context and lifespan_context.circuit_breaker_manager:
        manager = lifespan_context.circuit_breaker_manager
        if not isinstance(manager, KafkaCircuitBreakerManager):
            raise RuntimeError("Invalid circuit breaker manager type")
        return manager
    
    # Otherwise create a new one (for testing or standalone use)
    manager = KafkaCircuitBreakerManager()
    return manager


async def get_kafka_producer(request: Request) -> UnifiedProducer:
    # Check if producer is in lifespan context
    lifespan_context = getattr(request.app.state, 'lifespan_context', None)
    if lifespan_context and lifespan_context.kafka_producer:
        producer = lifespan_context.kafka_producer
        if not isinstance(producer, UnifiedProducer):
            raise RuntimeError("Invalid kafka producer type")
        return producer

    # Otherwise raise error - producer should be initialized in lifespan
    raise RuntimeError("Kafka Producer not initialized in lifespan context")


async def get_event_store(request: Request) -> EventStore:
    # Check if event store is in lifespan context
    lifespan_context = getattr(request.app.state, 'lifespan_context', None)
    if lifespan_context and lifespan_context.event_store:
        store = lifespan_context.event_store
        if not isinstance(store, EventStore):
            raise RuntimeError("Invalid event store type")
        return store

    # Otherwise raise error - event store should be initialized in lifespan
    raise RuntimeError("Event Store not initialized in lifespan context")


async def get_replay_service(
        database: Annotated[AsyncIOMotorDatabase, Depends(get_database)],
        kafka_producer: Annotated[UnifiedProducer, Depends(get_kafka_producer)],
        event_store: Annotated[EventStore, Depends(get_event_store)]
) -> EventReplayService:
    service = EventReplayService(
        database=database,
        producer=kafka_producer,
        event_store=event_store
    )
    # Initialize indexes on first call
    await service.initialize_indexes()
    return service


async def get_replay_repository(
        replay_service: Annotated[EventReplayService, Depends(get_replay_service)]
) -> ReplayRepository:
    return ReplayRepository(replay_service)


async def get_admin_events_repository(
        database: Annotated[AsyncIOMotorDatabase, Depends(get_database)]
) -> AdminEventsRepository:
    return AdminEventsRepository(database)


async def get_admin_settings_repository(
        database: Annotated[AsyncIOMotorDatabase, Depends(get_database)]
) -> AdminSettingsRepository:
    return AdminSettingsRepository(database)


async def get_admin_users_repository(
        database: Annotated[AsyncIOMotorDatabase, Depends(get_database)]
) -> AdminUserRepository:
    return AdminUserRepository(database)


async def get_connection_manager(request: Request) -> ConnectionManager:
    # Check if connection manager is in lifespan context
    lifespan_context = getattr(request.app.state, 'lifespan_context', None)
    if lifespan_context and lifespan_context.websocket_connection_manager:
        manager = lifespan_context.websocket_connection_manager
        if not isinstance(manager, ConnectionManager):
            raise RuntimeError("Invalid connection manager type")
        return manager

    # Otherwise raise error - connection manager should be initialized in lifespan
    raise RuntimeError("WebSocket Connection Manager not initialized in lifespan context")


async def get_websocket_auth(
        database: Annotated[AsyncIOMotorDatabase, Depends(get_database)]
) -> WebSocketAuth:
    return WebSocketAuth(database)


async def get_websocket_repository(
        database: Annotated[AsyncIOMotorDatabase, Depends(get_database)],
        connection_manager: Annotated[ConnectionManager, Depends(get_connection_manager)],
        websocket_auth: Annotated[WebSocketAuth, Depends(get_websocket_auth)],
        execution_repository: Annotated[ExecutionRepository, Depends(get_execution_repository)]
) -> WebSocketRepository:
    return WebSocketRepository(database, connection_manager, websocket_auth, execution_repository)


async def get_event_bus_manager() -> EventBusManager:
    return EventBusManager()


async def get_event_bus(
        manager: Annotated[EventBusManager, Depends(get_event_bus_manager)]
) -> EventBus:
    return await manager.get_event_bus()


async def get_kafka_event_service(
        event_repository: Annotated[EventRepository, Depends(get_event_repository)],
        kafka_producer: Annotated[UnifiedProducer, Depends(get_kafka_producer)]
) -> KafkaEventService:
    service = KafkaEventService(
        event_repository=event_repository,
        kafka_producer=kafka_producer
    )
    await service.initialize()
    return service


async def get_execution_service(
        execution_repository: Annotated[ExecutionRepository, Depends(get_execution_repository)],
        kafka_producer: Annotated[UnifiedProducer, Depends(get_kafka_producer)],
        event_store: Annotated[EventStore, Depends(get_event_store)]
) -> ExecutionService:
    settings = get_settings()

    return ExecutionService(
        execution_repo=execution_repository,
        producer=kafka_producer,
        event_store=event_store,
        settings=settings
    )


async def get_kubernetes_service(
        event_service: Annotated[KafkaEventService, Depends(get_kafka_event_service)]
) -> KubernetesService:
    service = KubernetesService()
    service.set_event_service(event_service)
    return service


async def get_schema_registry_manager(request: Request) -> SchemaRegistryManager:
    # Check if schema registry manager is in lifespan context
    lifespan_context = getattr(request.app.state, 'lifespan_context', None)
    if lifespan_context and lifespan_context.schema_registry_manager:
        manager = lifespan_context.schema_registry_manager
        if not isinstance(manager, SchemaRegistryManager):
            raise RuntimeError("Invalid schema registry manager type")
        return manager

    # Otherwise raise error - schema registry manager should be initialized in lifespan
    raise RuntimeError("Schema Registry Manager not initialized in lifespan context")


async def get_notification_service(
        request: Request,
        notification_repository: Annotated[NotificationRepository, Depends(get_notification_repository)],
        event_service: Annotated[KafkaEventService, Depends(get_kafka_event_service)],
        event_bus_manager: Annotated[EventBusManager, Depends(get_event_bus_manager)],
        schema_registry_manager: Annotated[SchemaRegistryManager, Depends(get_schema_registry_manager)]
) -> NotificationService:
    # Check if notification service is already running in lifespan context
    lifespan_context = getattr(request.app.state, 'lifespan_context', None)
    if lifespan_context and lifespan_context.notification_service:
        service = lifespan_context.notification_service
        if not isinstance(service, NotificationService):
            raise RuntimeError("Invalid notification service type")
        return service

    # Otherwise create a new instance (for testing or standalone use)
    service = NotificationService(
        notification_repository=notification_repository,
        event_service=event_service,
        event_bus_manager=event_bus_manager,
        schema_registry_manager=schema_registry_manager
    )
    # Don't initialize here since it won't consume events without the consumer running
    return service


async def get_user_settings_service(
        database: Annotated[AsyncIOMotorDatabase, Depends(get_database)],
        event_service: Annotated[KafkaEventService, Depends(get_kafka_event_service)]
) -> UserSettingsService:
    service = UserSettingsService(database, event_service)
    await service.initialize()
    return service


async def get_saga_config() -> SagaConfig:
    return SagaConfig(
        name="default",
        timeout_seconds=300,
        max_retries=3,
        retry_delay_seconds=5,
        enable_compensation=True,
        store_events=True
    )


async def get_saga_orchestrator(
        request: Request,
        saga_config: Annotated[SagaConfig, Depends(get_saga_config)],
        database: Annotated[AsyncIOMotorDatabase, Depends(get_database)],
        kafka_producer: Annotated[UnifiedProducer, Depends(get_kafka_producer)],
        schema_registry_manager: Annotated[SchemaRegistryManager, Depends(get_schema_registry_manager)],
        event_store: Annotated[EventStore, Depends(get_event_store)]
) -> SagaOrchestrator:
    # Check if saga orchestrator is in lifespan context
    lifespan_context = getattr(request.app.state, 'lifespan_context', None)
    if lifespan_context and lifespan_context.saga_orchestrator:
        orchestrator = lifespan_context.saga_orchestrator
        if not isinstance(orchestrator, SagaOrchestrator):
            raise RuntimeError("Invalid saga orchestrator type")
        return orchestrator
    
    # Otherwise create a new one (for testing or standalone use)
    return SagaOrchestrator(saga_config, database, kafka_producer, schema_registry_manager, event_store)


async def get_websocket_event_handler(request: Request) -> WebSocketEventHandler:
    # Check if handler is in lifespan context
    lifespan_context = getattr(request.app.state, 'lifespan_context', None)
    if lifespan_context and lifespan_context.websocket_event_handler:
        handler = lifespan_context.websocket_event_handler
        if not isinstance(handler, WebSocketEventHandler):
            raise RuntimeError("Invalid websocket event handler type")
        return handler

    # Otherwise create a new one (for testing or standalone use)
    handler = WebSocketEventHandler()
    await handler.start()
    return handler


async def get_saved_script_service(
        saved_script_repository: Annotated[SavedScriptRepository, Depends(get_saved_script_repository)]
) -> SavedScriptService:
    return SavedScriptService(saved_script_repository)


async def get_dlq_manager(request: Request) -> DLQManager:
    # Check if DLQ manager is in lifespan context
    lifespan_context = getattr(request.app.state, 'lifespan_context', None)
    if lifespan_context and lifespan_context.dlq_manager:
        manager = lifespan_context.dlq_manager
        if not isinstance(manager, DLQManager):
            raise RuntimeError("Invalid DLQ manager type")
        return manager

    # Otherwise raise error - DLQ manager should be initialized in lifespan
    raise RuntimeError("DLQ Manager not initialized in lifespan context")


async def get_dlq_consumer_registry(request: Request) -> DLQConsumerRegistry:
    # Check if DLQ consumer registry is in lifespan context
    lifespan_context = getattr(request.app.state, 'lifespan_context', None)
    if lifespan_context and lifespan_context.dlq_consumer_registry:
        registry = lifespan_context.dlq_consumer_registry
        if not isinstance(registry, DLQConsumerRegistry):
            raise RuntimeError("Invalid DLQ consumer registry type")
        return registry

    # Otherwise raise error - DLQ consumer registry should be initialized in lifespan
    raise RuntimeError("DLQ Consumer Registry not initialized in lifespan context")


async def get_idempotency_manager(request: Request) -> IdempotencyManager:
    # Check if idempotency manager is in lifespan context
    lifespan_context = getattr(request.app.state, 'lifespan_context', None)
    if lifespan_context and lifespan_context.idempotency_manager:
        manager = lifespan_context.idempotency_manager
        if not isinstance(manager, IdempotencyManager):
            raise RuntimeError("Invalid idempotency manager type")
        return manager

    # Otherwise raise error - idempotency manager should be initialized in lifespan
    raise RuntimeError("Idempotency Manager not initialized in lifespan context")


async def get_sse_shutdown_manager(request: Request) -> SSEShutdownManager:
    # Check if SSE shutdown manager is in lifespan context
    lifespan_context = getattr(request.app.state, 'lifespan_context', None)
    if lifespan_context and lifespan_context.sse_shutdown_manager:
        manager = lifespan_context.sse_shutdown_manager
        if not isinstance(manager, SSEShutdownManager):
            raise RuntimeError("Invalid SSE shutdown manager type")
        return manager

    # Otherwise raise error - SSE shutdown manager should be initialized in lifespan
    raise RuntimeError("SSE Shutdown Manager not initialized in lifespan context")


async def get_sse_connection_manager(request: Request) -> SSEConnectionManager:
    # Check if SSE connection manager is in lifespan context
    lifespan_context = getattr(request.app.state, 'lifespan_context', None)
    if lifespan_context and lifespan_context.sse_connection_manager:
        manager = lifespan_context.sse_connection_manager
        if not isinstance(manager, SSEConnectionManager):
            raise RuntimeError("Invalid SSE connection manager type")
        return manager

    # Otherwise raise error - SSE connection manager should be initialized in lifespan
    raise RuntimeError("SSE Connection Manager not initialized in lifespan context")


class LifespanContext:
    def __init__(self) -> None:
        self.event_store: EventStore | None = None
        self.event_store_consumer: EventStoreConsumer | None = None
        self.health_check_tasks: list[asyncio.Task[None]] = []
        self.background_tasks: list[asyncio.Task[None]] = []
        self.k8s_daemonset_task: asyncio.Task[None] | None = None
        self.notification_service: NotificationService | None = None
        self.saga_orchestrator: SagaOrchestrator | None = None
        self.websocket_event_handler: WebSocketEventHandler | None = None
        self.dlq_manager: DLQManager | None = None
        self.dlq_consumer_registry: DLQConsumerRegistry | None = None
        self.idempotency_manager: IdempotencyManager | None = None
        self.kafka_producer: UnifiedProducer | None = None
        self.kafka_metrics_service: KafkaMetricsService | None = None
        self.schema_registry_manager: SchemaRegistryManager | None = None
        self.sse_shutdown_manager: SSEShutdownManager | None = None
        self.sse_connection_manager: SSEConnectionManager | None = None
        self.websocket_connection_manager: ConnectionManager | None = None
        self.circuit_breaker_manager: KafkaCircuitBreakerManager | None = None

    async def cleanup(self) -> None:
        for task in self.background_tasks:
            if not task.done():
                task.cancel()

        if self.event_store_consumer:
            await self.event_store_consumer.stop()

        if self.notification_service:
            await self.notification_service.shutdown()

        if self.websocket_event_handler:
            await self.websocket_event_handler.stop()

        if self.dlq_manager:
            await self.dlq_manager.stop()

        if self.dlq_consumer_registry:
            await self.dlq_consumer_registry.stop_all()

        if self.idempotency_manager:
            await self.idempotency_manager.close()

        if self.kafka_producer:
            await self.kafka_producer.stop()

        if self.kafka_metrics_service:
            await self.kafka_metrics_service.shutdown()

        if self.sse_shutdown_manager and self.sse_shutdown_manager.is_shutting_down():
            await self.sse_shutdown_manager.wait_for_shutdown()


async def get_lifespan_context(request: Request) -> LifespanContext:
    if not hasattr(request.app.state, 'lifespan_context'):
        raise RuntimeError("Lifespan context not initialized")
    context = request.app.state.lifespan_context
    if not isinstance(context, LifespanContext):
        raise RuntimeError("Invalid lifespan context type")
    return context


# Type aliases
DatabaseDep = Annotated[AsyncIOMotorDatabase, Depends(get_database)]
ConnectionManagerDep = Annotated[ConnectionManager, Depends(get_connection_manager)]
WebSocketAuthDep = Annotated[WebSocketAuth, Depends(get_websocket_auth)]
SagaConfigDep = Annotated[SagaConfig, Depends(get_saga_config)]
EventRepositoryDep = Annotated[EventRepository, Depends(get_event_repository)]
ExecutionRepositoryDep = Annotated[ExecutionRepository, Depends(get_execution_repository)]
NotificationRepositoryDep = Annotated[NotificationRepository, Depends(get_notification_repository)]
ProjectionRepositoryDep = Annotated[ProjectionRepository, Depends(get_projection_repository)]
SagaRepositoryDep = Annotated[SagaRepository, Depends(get_saga_repository)]
SavedScriptRepositoryDep = Annotated[SavedScriptRepository, Depends(get_saved_script_repository)]
SSERepositoryDep = Annotated[SSERepository, Depends(get_sse_repository)]
UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]
DLQRepositoryDep = Annotated[DLQRepository, Depends(get_dlq_repository)]
HealthDashboardRepositoryDep = Annotated[HealthDashboardRepository, Depends(get_health_dashboard_repository)]
KafkaMetricsRepositoryDep = Annotated[KafkaMetricsRepository, Depends(get_kafka_metrics_repository)]
ReplayRepositoryDep = Annotated[ReplayRepository, Depends(get_replay_repository)]
AdminEventsRepositoryDep = Annotated[AdminEventsRepository, Depends(get_admin_events_repository)]
AdminSettingsRepositoryDep = Annotated[AdminSettingsRepository, Depends(get_admin_settings_repository)]
AdminUserRepositoryDep = Annotated[AdminUserRepository, Depends(get_admin_users_repository)]
WebSocketRepositoryDep = Annotated[WebSocketRepository, Depends(get_websocket_repository)]

EventBusDep = Annotated[EventBus, Depends(get_event_bus)]
EventStoreDep = Annotated[EventStore, Depends(get_event_store)]
KafkaProducerDep = Annotated[UnifiedProducer, Depends(get_kafka_producer)]
KafkaEventServiceDep = Annotated[KafkaEventService, Depends(get_kafka_event_service)]
ExecutionServiceDep = Annotated[ExecutionService, Depends(get_execution_service)]
KubernetesServiceDep = Annotated[KubernetesService, Depends(get_kubernetes_service)]
NotificationServiceDep = Annotated[NotificationService, Depends(get_notification_service)]
UserSettingsServiceDep = Annotated[UserSettingsService, Depends(get_user_settings_service)]
ProjectionServiceDep = Annotated[EventProjectionService, Depends(get_projection_service)]
SagaOrchestratorDep = Annotated[SagaOrchestrator, Depends(get_saga_orchestrator)]
KafkaMetricsServiceDep = Annotated[KafkaMetricsService, Depends(get_kafka_metrics_service)]
WebSocketEventHandlerDep = Annotated[WebSocketEventHandler, Depends(get_websocket_event_handler)]
SavedScriptServiceDep = Annotated[SavedScriptService, Depends(get_saved_script_service)]
EventReplayServiceDep = Annotated[EventReplayService, Depends(get_replay_service)]
LifespanContextDep = Annotated[LifespanContext, Depends(get_lifespan_context)]
DLQConsumerRegistryDep = Annotated[DLQConsumerRegistry, Depends(get_dlq_consumer_registry)]
IdempotencyManagerDep = Annotated[IdempotencyManager, Depends(get_idempotency_manager)]
SSEShutdownManagerDep = Annotated[SSEShutdownManager, Depends(get_sse_shutdown_manager)]
SSEConnectionManagerDep = Annotated[SSEConnectionManager, Depends(get_sse_connection_manager)]
CircuitBreakerManagerDep = Annotated[KafkaCircuitBreakerManager, Depends(get_circuit_breaker_manager)]
