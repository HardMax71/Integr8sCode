import asyncio
import contextlib
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api.routes import (
    alertmanager,
    auth,
    circuit_breaker,
    dlq,
    events,
    execution,
    health_dashboard,
    kafka_metrics,
    notifications,
    projections,
    replay,
    saga,
    saved_scripts,
    sse,
    user_settings,
    websocket,
)
from app.api.routes.admin import (
    events_router as admin_events_router,
)
from app.api.routes.admin import (
    settings_router as admin_settings_router,
)
from app.api.routes.admin import (
    users_router as admin_users_router,
)
from app.config import Settings, get_settings
from app.core.cache_middleware import CacheControlMiddleware
from app.core.correlation import CorrelationMiddleware
from app.core.database_context import (
    AsyncDatabaseConnection,
    DatabaseConfig,
    DatabaseProvider,
    create_contextual_provider,
    create_database_connection,
    get_database_provider,
)
from app.core.exceptions import configure_exception_handlers
from app.core.logging import logger
from app.core.middleware import RequestSizeLimitMiddleware
from app.core.service_dependencies import LifespanContext
from app.core.tracing import init_tracing
from app.db.repositories.event_repository import EventRepository
from app.db.repositories.notification_repository import NotificationRepository
from app.dlq.consumer import DLQConsumerRegistry
from app.dlq.manager import DLQManager, create_dlq_manager
from app.events.core.producer import UnifiedProducer, create_unified_producer
from app.events.kafka.metrics.metrics_service import KafkaMetricsService
from app.events.schema.schema_registry import (
    SchemaRegistryManager,
    create_schema_registry_manager,
    initialize_event_schemas,
)
from app.events.store.event_store import EventStore, create_event_store, create_event_store_consumer
from app.schemas_avro.event_schemas import get_all_topics
from app.services.event_bus import EventBusManager
from app.services.event_projections import EventProjectionService
from app.services.health_service import initialize_health_checks, shutdown_health_checks
from app.services.idempotency import IdempotencyManager, create_idempotency_manager
from app.services.kafka_event_service import KafkaEventService
from app.services.kubernetes_service import KubernetesService
from app.services.notification_service import NotificationService
from app.services.saga.saga_orchestrator import SagaOrchestrator, create_saga_orchestrator
from app.services.sse_connection_manager import SSEConnectionManager, create_sse_connection_manager
from app.services.sse_shutdown_manager import SSEShutdownManager, create_sse_shutdown_manager
from app.websocket.connection_manager import ConnectionManager, create_connection_manager
from app.websocket.event_handler import WebSocketEventHandler


class StartupContext:
    """Container for services initialized during startup."""

    def __init__(self) -> None:
        self.db_connection: AsyncDatabaseConnection | None = None
        self.k8s_service: KubernetesService | None = None
        self.dlq_manager: DLQManager | None = None
        self.idempotency_manager: IdempotencyManager | None = None
        self.sse_shutdown_manager: SSEShutdownManager | None = None
        self.kafka_metrics_service: KafkaMetricsService | None = None
        self.event_bus_manager: EventBusManager | None = None
        self.schema_registry_manager: SchemaRegistryManager | None = None
        self.sse_connection_manager: SSEConnectionManager | None = None
        self.websocket_connection_manager: ConnectionManager | None = None
        self.kafka_producer: UnifiedProducer | None = None
        self.websocket_event_handler: WebSocketEventHandler | None = None
        self.projection_service: EventProjectionService | None = None
        self.kafka_event_service: KafkaEventService | None = None
        self.notification_service: NotificationService | None = None
        self.saga_orchestrator: SagaOrchestrator | None = None
        self.event_store: EventStore | None = None


async def initialize_database(settings: Settings, startup_ctx: StartupContext) -> None:
    """Initialize database connection."""
    db_config = DatabaseConfig(
        mongodb_url=settings.MONGODB_URL,
        db_name=settings.PROJECT_NAME + "_test" if settings.TESTING else settings.PROJECT_NAME,
        server_selection_timeout_ms=5000,
        connect_timeout_ms=5000,
        max_pool_size=50,
        min_pool_size=10
    )

    startup_ctx.db_connection = create_database_connection(db_config)
    await startup_ctx.db_connection.connect()
    logger.info("Database connection established.")


async def initialize_core_services(startup_ctx: StartupContext, lifespan_context: LifespanContext) -> None:
    """Initialize core services like DLQ, idempotency, SSE managers."""
    # Validate db_connection is available
    if not startup_ctx.db_connection:
        raise RuntimeError("Database connection not initialized")

    # DLQ Manager
    logger.info("Initializing DLQ manager...")
    startup_ctx.dlq_manager = create_dlq_manager(startup_ctx.db_connection.database)
    await startup_ctx.dlq_manager.start()
    lifespan_context.dlq_manager = startup_ctx.dlq_manager
    logger.info("DLQ manager initialized and started")

    # DLQ Consumer Registry
    logger.info("Initializing DLQ consumer registry...")
    lifespan_context.dlq_consumer_registry = DLQConsumerRegistry()
    logger.info("DLQ consumer registry initialized")

    # Idempotency Manager
    logger.info("Initializing idempotency manager...")
    startup_ctx.idempotency_manager = create_idempotency_manager(startup_ctx.db_connection.database)
    await startup_ctx.idempotency_manager.initialize()
    lifespan_context.idempotency_manager = startup_ctx.idempotency_manager
    logger.info("Idempotency manager initialized")

    # SSE Shutdown Manager
    logger.info("Initializing SSE shutdown manager...")
    startup_ctx.sse_shutdown_manager = create_sse_shutdown_manager()
    lifespan_context.sse_shutdown_manager = startup_ctx.sse_shutdown_manager
    logger.info("SSE shutdown manager initialized")


async def initialize_kafka_services(startup_ctx: StartupContext, lifespan_context: LifespanContext) -> None:
    """Initialize Kafka-related services."""
    # Schema Registry
    logger.info("Initializing schema registry...")
    startup_ctx.schema_registry_manager = create_schema_registry_manager()
    await initialize_event_schemas(startup_ctx.schema_registry_manager)
    lifespan_context.schema_registry_manager = startup_ctx.schema_registry_manager
    logger.info("Schema registry initialized")

    # Kafka Producer
    logger.info("Initializing Kafka producer...")
    startup_ctx.kafka_producer = create_unified_producer(schema_registry_manager=startup_ctx.schema_registry_manager)
    await startup_ctx.kafka_producer.start()
    lifespan_context.kafka_producer = startup_ctx.kafka_producer
    logger.info("Kafka producer initialized and started")

    # Kafka Metrics
    logger.info("Initializing Kafka metrics collection...")
    startup_ctx.kafka_metrics_service = KafkaMetricsService()
    await startup_ctx.kafka_metrics_service.initialize()
    lifespan_context.kafka_metrics_service = startup_ctx.kafka_metrics_service
    logger.info("Kafka metrics collection initialized")
    
    # Circuit Breaker Manager
    logger.info("Initializing circuit breaker manager...")
    from app.events.kafka.cb import KafkaCircuitBreakerManager
    lifespan_context.circuit_breaker_manager = KafkaCircuitBreakerManager()
    logger.info("Circuit breaker manager initialized")

    # Event Store
    logger.info("Initializing event store...")
    if not startup_ctx.db_connection or not startup_ctx.db_connection.is_connected():
        raise RuntimeError("Database connection not established.")

    # Create event store
    startup_ctx.event_store = create_event_store(
        db=startup_ctx.db_connection.database,
        ttl_days=90
    )
    await startup_ctx.event_store.initialize()
    lifespan_context.event_store = startup_ctx.event_store
    logger.info("Event store initialized")

    # Event Store Consumer
    logger.info("Initializing event store consumer...")
    event_store_topics = get_all_topics()
    logger.info(f"Subscribing to {len(event_store_topics)} Kafka topics")

    # Create and start event store consumer
    event_store_consumer = create_event_store_consumer(
        event_store=startup_ctx.event_store,
        topics=list(event_store_topics),
        schema_registry_manager=startup_ctx.schema_registry_manager
    )
    await event_store_consumer.start()
    lifespan_context.event_store_consumer = event_store_consumer
    logger.info("Event store consumer started")


async def initialize_websocket_services(startup_ctx: StartupContext, lifespan_context: LifespanContext) -> None:
    """Initialize WebSocket and SSE services."""
    # SSE Connection Manager
    logger.info("Initializing SSE connection manager...")
    startup_ctx.sse_connection_manager = create_sse_connection_manager(
        schema_registry_manager=startup_ctx.schema_registry_manager,
        shutdown_manager=startup_ctx.sse_shutdown_manager
    )
    lifespan_context.sse_connection_manager = startup_ctx.sse_connection_manager
    logger.info("SSE connection manager initialized")

    # WebSocket Connection Manager
    logger.info("Initializing WebSocket connection manager...")
    startup_ctx.websocket_connection_manager = create_connection_manager()
    lifespan_context.websocket_connection_manager = startup_ctx.websocket_connection_manager
    logger.info("WebSocket connection manager initialized")

    # WebSocket Event Handler
    logger.info("Starting WebSocket event handler...")
    startup_ctx.websocket_event_handler = WebSocketEventHandler(
        schema_registry_manager=startup_ctx.schema_registry_manager,
        connection_manager=startup_ctx.websocket_connection_manager
    )
    await startup_ctx.websocket_event_handler.start()
    lifespan_context.websocket_event_handler = startup_ctx.websocket_event_handler
    logger.info("WebSocket event handler started")


async def initialize_business_services(startup_ctx: StartupContext, lifespan_context: LifespanContext) -> None:
    """Initialize business logic services."""
    # Event Bus
    logger.info("Initializing event bus...")
    startup_ctx.event_bus_manager = EventBusManager()
    await startup_ctx.event_bus_manager.get_event_bus()
    logger.info("Event bus initialized")

    # Validate database connection
    if not startup_ctx.db_connection:
        raise RuntimeError("Database connection not initialized")

    # Projection Service
    logger.info("Initializing projection service...")
    startup_ctx.projection_service = EventProjectionService(startup_ctx.db_connection.database)
    await startup_ctx.projection_service.initialize()

    projection_names = startup_ctx.projection_service.get_projection_names()
    logger.info(f"Starting {len(projection_names)} projections: {', '.join(projection_names)}")

    for projection_name in projection_names:
        await startup_ctx.projection_service.start_projection(projection_name)

    logger.info("Projection service initialized with all registered projections")

    # Kafka Event Service
    notification_repository = NotificationRepository(startup_ctx.db_connection.database)
    if not startup_ctx.kafka_producer:
        raise RuntimeError("Kafka producer not initialized")
    startup_ctx.kafka_event_service = KafkaEventService(
        event_repository=EventRepository(startup_ctx.db_connection.database),
        kafka_producer=startup_ctx.kafka_producer
    )
    await startup_ctx.kafka_event_service.initialize()

    # Notification Service
    logger.info("Initializing notification service...")
    startup_ctx.notification_service = NotificationService(
        notification_repository=notification_repository,
        event_service=startup_ctx.kafka_event_service,
        event_bus_manager=startup_ctx.event_bus_manager,
        schema_registry_manager=startup_ctx.schema_registry_manager
    )
    await startup_ctx.notification_service.initialize()
    lifespan_context.notification_service = startup_ctx.notification_service
    logger.info("Notification service initialized and consuming events")

    # Saga Orchestrator
    logger.info("Initializing saga orchestrator...")
    if not startup_ctx.db_connection or not startup_ctx.kafka_producer:
        raise RuntimeError("Database connection or Kafka producer not initialized")
    startup_ctx.saga_orchestrator = create_saga_orchestrator(
        database=startup_ctx.db_connection.database,
        producer=startup_ctx.kafka_producer,
        schema_registry_manager=startup_ctx.schema_registry_manager,
        event_store=startup_ctx.event_store
    )
    lifespan_context.saga_orchestrator = startup_ctx.saga_orchestrator
    logger.info("Saga orchestrator initialized")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup
    settings: Settings = get_settings()
    logger.info(
        "Starting application",
        extra={
            "project_name": settings.PROJECT_NAME,
            "environment": "test" if settings.TESTING else "production",
        },
    )

    init_tracing(
        service_name=settings.TRACING_SERVICE_NAME,
        service_version=settings.TRACING_SERVICE_VERSION,
        sampling_rate=settings.TRACING_SAMPLING_RATE,
        enable_console_exporter=settings.TESTING,
        adaptive_sampling=settings.TRACING_ADAPTIVE_SAMPLING
    )
    logger.info("Distributed tracing initialized")

    # Initialize startup context
    startup_ctx = StartupContext()

    try:
        # Initialize database
        await initialize_database(settings, startup_ctx)

        # Create contextual provider for request-scoped access
        db_provider = create_contextual_provider()

        # Set up dependency override for database provider
        async def override_get_database_provider() -> DatabaseProvider:
            if not startup_ctx.db_connection:
                raise RuntimeError("Database connection not initialized")
            db_provider.set_connection(startup_ctx.db_connection)
            return db_provider

        app.dependency_overrides[get_database_provider] = override_get_database_provider

        # Create lifespan context for background services
        lifespan_context = LifespanContext()
        app.state.lifespan_context = lifespan_context
        app.state.db_connection = startup_ctx.db_connection  # Store for shutdown
        logger.info("Database dependency injection configured.")

        # Initialize Kubernetes service for daemonset
        startup_ctx.k8s_service = KubernetesService()
        lifespan_context.k8s_daemonset_task = asyncio.create_task(  # type: ignore[assignment]
            startup_ctx.k8s_service.ensure_image_pre_puller_daemonset()
        )
        logger.info("Kubernetes image pre-puller daemonset task scheduled.")

        # Initialize core services
        await initialize_core_services(startup_ctx, lifespan_context)

        # Initialize Kafka services first (needed for health checks)
        await initialize_kafka_services(startup_ctx, lifespan_context)

        # Initialize health checks (after Kafka producer is available)
        logger.info("Initializing health check system...")
        if not startup_ctx.db_connection:
            raise RuntimeError("Database connection not initialized")
        await initialize_health_checks(
            startup_ctx.db_connection.database,
            startup_ctx.dlq_manager,
            startup_ctx.idempotency_manager,
            startup_ctx.kafka_producer,
            startup_ctx.event_store
        )
        logger.info("Health check system initialized")

        # Initialize WebSocket/SSE services
        await initialize_websocket_services(startup_ctx, lifespan_context)

        # Initialize business services
        await initialize_business_services(startup_ctx, lifespan_context)

        # EventReplayService now uses dependency injection instead of singleton

    except ConnectionError as e:
        logger.critical(f"Failed to connect to database: {e}", extra={"error": str(e)})
        raise RuntimeError("Application startup failed: Could not connect to database.") from e
    except Exception as e:
        logger.critical(f"Failed during application startup: {e}", extra={"error": str(e)})
        logger.info("Attempting to close database connection after startup failure...")
        if startup_ctx.db_connection:
            try:
                await startup_ctx.db_connection.disconnect()
            except Exception:
                pass  # Connection might not have been fully established
        raise

    yield

    # Shutdown
    try:
        # Get lifespan context from app state
        shutdown_context: LifespanContext | None = getattr(app.state, 'lifespan_context', None)

        # Initiate SSE shutdown if manager exists
        sse_shutdown_task = None
        if shutdown_context and shutdown_context.sse_shutdown_manager:
            logger.info("Initiating SSE connection draining...")
            sse_shutdown_task = asyncio.create_task(shutdown_context.sse_shutdown_manager.initiate_shutdown())

        if shutdown_context:
            # Cancel background tasks
            await shutdown_context.cleanup()

            # Cancel daemonset task
            if shutdown_context.k8s_daemonset_task and not shutdown_context.k8s_daemonset_task.done():
                shutdown_context.k8s_daemonset_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await shutdown_context.k8s_daemonset_task
                logger.info("Image pre-puller daemonset task cancelled successfully.")

        # Idempotency manager will be closed via lifespan_context.cleanup()

        # Shutdown health check system
        logger.info("Shutting down health check system...")
        await shutdown_health_checks()
        logger.info("Health check system shut down")

        # Kafka metrics shutdown happens via background task cancellation

        # Services will be cleaned up through dependency injection lifecycle

        # Event store consumer shutdown happens via lifespan_context.cleanup()

        # Kafka producer will be closed via lifespan_context.cleanup()

        # Close database connection
        if hasattr(app.state, "db_connection") and app.state.db_connection:
            logger.info("Closing database connection...")
            await app.state.db_connection.disconnect()
            logger.info("Database connection closed.")

        # Wait for SSE shutdown to complete
        if sse_shutdown_task is not None:
            logger.info("Waiting for SSE shutdown to complete...")
            try:
                await asyncio.wait_for(sse_shutdown_task, timeout=45.0)
                logger.info("SSE shutdown completed")
            except asyncio.TimeoutError:
                logger.error("SSE shutdown timed out after 45 seconds")

            # Log final SSE shutdown status
            if shutdown_context and shutdown_context.sse_shutdown_manager:
                shutdown_status = shutdown_context.sse_shutdown_manager.get_shutdown_status()
                logger.info(f"SSE shutdown status: {shutdown_status}")

    except Exception as e:
        logger.error("Error during application shutdown", extra={"error": str(e)})


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

    app.add_middleware(CorrelationMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(CacheControlMiddleware)

    limiter = Limiter(key_func=get_remote_address, default_limits=[settings.RATE_LIMITS])
    logger.info(f"RATE LIMITING [TESTING={settings.TESTING}] enabled with limits: {settings.RATE_LIMITS}")

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://localhost:5001",
            "https://127.0.0.1:5001",
            "https://localhost",
            "https://127.0.0.1",
            "https://localhost:443",
            "https://127.0.0.1:443",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "Origin",
            "X-Requested-With",
            "X-CSRF-Token",
            "X-Correlation-ID",
            "X-Request-ID",
        ],
        expose_headers=["Content-Length", "Content-Range", "X-Correlation-ID"],
    )
    logger.info("CORS middleware configured")

    app.add_middleware(SlowAPIMiddleware)

    app.include_router(auth.router, prefix=settings.API_V1_STR)
    app.include_router(execution.router, prefix=settings.API_V1_STR)
    app.include_router(saved_scripts.router, prefix=settings.API_V1_STR)
    app.include_router(websocket.router, prefix=settings.API_V1_STR)
    app.include_router(replay.router, prefix=settings.API_V1_STR)
    app.include_router(circuit_breaker.router, prefix=settings.API_V1_STR)
    app.include_router(health_dashboard.router, prefix=settings.API_V1_STR)
    app.include_router(dlq.router, prefix=settings.API_V1_STR)
    app.include_router(sse.router, prefix=settings.API_V1_STR)
    app.include_router(events.router, prefix=settings.API_V1_STR)
    app.include_router(projections.router, prefix=settings.API_V1_STR)
    app.include_router(admin_events_router, prefix=settings.API_V1_STR)
    app.include_router(admin_settings_router, prefix=settings.API_V1_STR)
    app.include_router(admin_users_router, prefix=settings.API_V1_STR)
    app.include_router(user_settings.router, prefix=settings.API_V1_STR)
    app.include_router(notifications.router, prefix=settings.API_V1_STR)
    app.include_router(saga.router, prefix=settings.API_V1_STR)
    app.include_router(kafka_metrics.router, prefix=settings.API_V1_STR)
    app.include_router(alertmanager.router, prefix=settings.API_V1_STR)

    logger.info("All routers configured")

    configure_exception_handlers(app)
    logger.info("Exception handlers configured")

    Instrumentator().instrument(app).expose(app)
    logger.info("Prometheus instrumentator configured")

    return app


app = create_app()

if __name__ == "__main__":
    settings = get_settings()

    logger.info(
        "Starting uvicorn server",
        extra={"host": settings.SERVER_HOST,
               "port": settings.SERVER_PORT,
               "ssl_enabled": True},
    )
    uvicorn.run(
        app,
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        ssl_keyfile=settings.SSL_KEYFILE,
        ssl_certfile=settings.SSL_CERTFILE,
    )
