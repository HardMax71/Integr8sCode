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
from app.core.exceptions import configure_exception_handlers
from app.core.logging import logger
from app.core.middleware import RequestSizeLimitMiddleware
from app.core.tracing import init_tracing
from app.db.mongodb import DatabaseManager
from app.db.repositories.event_repository import EventRepository
from app.dlq.manager import DLQManagerSingleton
from app.events.core.producer import close_producer, get_producer
from app.events.kafka.metrics.metrics_service import KafkaMetricsService
from app.events.store.event_store import start_event_store_consumer, stop_event_store_consumer
from app.schemas_avro.event_schemas import get_all_topics
from app.services.event_bus import EventBusManager
from app.services.event_projections import EventProjectionManager
from app.services.event_replay.replay_service import EventReplayServiceSingleton
from app.services.health_service import initialize_health_checks, shutdown_health_checks
from app.services.idempotency import close_idempotency_manager
from app.services.idempotency.idempotency_manager import IdempotencyManagerSingleton
from app.services.kafka_event_service import KafkaEventService, KafkaEventServiceManager
from app.services.kubernetes_service import KubernetesService, KubernetesServiceManager
from app.services.notification_service import NotificationManager
from app.services.saga.saga_manager import SagaOrchestratorManagerSingleton, get_saga_orchestrator_manager
from app.services.sse_shutdown_manager import get_sse_shutdown_manager
from app.services.user_settings_service import UserSettingsManager
from app.websocket.event_handler import get_websocket_event_handler


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

    db_manager = DatabaseManager(settings)
    try:
        await db_manager.connect_to_database()
        app.state.db_manager = db_manager
        logger.info("DatabaseManager initialized and connected.")

        k8s_manager = KubernetesServiceManager()
        app.state.k8s_manager = k8s_manager
        logger.info("Kubernetes service manager initialized")

        k8s_service = KubernetesService(k8s_manager)
        app.state.k8s_service = k8s_service
        logger.info("KubernetesService singleton instance created.")

        daemonset_task = asyncio.create_task(k8s_service.ensure_image_pre_puller_daemonset())
        app.state.daemonset_task = daemonset_task
        logger.info("Kubernetes image pre-puller daemonset task scheduled.")

        logger.info("Starting WebSocket event handler...")
        websocket_event_handler = get_websocket_event_handler()
        await websocket_event_handler.start()
        app.state.websocket_handler = websocket_event_handler
        logger.info("WebSocket event handler started")

        logger.info("Initializing health check system...")
        await initialize_health_checks(db_manager)
        logger.info("Health check system initialized")

        logger.info("Initializing Kafka metrics collection...")
        kafka_metrics_service = KafkaMetricsService()
        await kafka_metrics_service.initialize()
        app.state.kafka_metrics_service = kafka_metrics_service
        logger.info("Kafka metrics collection initialized")

        logger.info("Initializing event store consumer...")
        event_store_topics = get_all_topics()
        logger.info(f"Subscribing to {len(event_store_topics)} Kafka topics")

        if db_manager.db is None:
            raise RuntimeError("Database connection failed.")

        event_store_consumer = await start_event_store_consumer(
            db_manager.db,
            list(event_store_topics),
            ttl_days=90
        )
        app.state.event_store_consumer = event_store_consumer
        logger.info("Event store consumer initialized and started")

        logger.info("Initializing event bus...")
        event_bus_manager = EventBusManager()
        app.state.event_bus_manager = event_bus_manager
        event_bus = await event_bus_manager.get_event_bus()
        logger.info("Event bus initialized")

        logger.info("Initializing Kafka producer...")
        producer = await get_producer()
        logger.info("Kafka producer initialized and started")

        logger.info("Initializing event service...")
        event_repository = EventRepository(db_manager)
        await event_repository.initialize()

        logger.info("Initializing Kafka-based event service")
        kafka_event_service_manager = KafkaEventServiceManager()
        event_service: KafkaEventService = await kafka_event_service_manager.get_service(db_manager)
        app.state.event_service_manager = kafka_event_service_manager
        logger.info("Kafka event service initialized")

        k8s_service.set_event_service(event_service)
        logger.info("Event service configured for Kubernetes service")

        logger.info("Initializing projection service...")
        projection_manager = EventProjectionManager()
        projection_service = await projection_manager.get_service(db_manager)
        app.state.projection_manager = projection_manager

        # Start all registered projections
        projection_names = projection_service.get_projection_names()
        logger.info(f"Starting {len(projection_names)} projections: {', '.join(projection_names)}")

        for projection_name in projection_names:
            await projection_service.start_projection(projection_name)

        logger.info("Projection service initialized with all registered projections")

        logger.info("Initializing user settings service...")
        settings_manager = UserSettingsManager()
        settings_service = await settings_manager.get_service(db_manager, event_service)
        app.state.settings_manager = settings_manager
        logger.info("User settings service initialized")

        logger.info("Initializing notification service...")
        notification_manager = NotificationManager()
        notification_service = await notification_manager.get_service(db_manager, event_service, event_bus_manager)
        app.state.notification_manager = notification_manager
        logger.info("Notification service initialized")

        logger.info("Initializing idempotency manager...")
        await IdempotencyManagerSingleton.get_instance(db_manager)
        logger.info("Idempotency manager initialized")

        logger.info("Initializing saga orchestrator...")
        SagaOrchestratorManagerSingleton.set_database_manager(db_manager)
        saga_manager = await get_saga_orchestrator_manager()
        app.state.saga_manager = saga_manager
        # Get orchestrator to initialize it (but don't start it in web app)
        saga_orchestrator = await saga_manager.get_orchestrator()
        logger.info("Saga orchestrator initialized")

        DLQManagerSingleton.set_database_manager(db_manager)
        logger.info("DLQManagerSingleton database manager set")

        EventReplayServiceSingleton.set_database_manager(db_manager)
        logger.info("EventReplayServiceSingleton database manager set")
    except ConnectionError as e:
        logger.critical(f"Failed to initialize DatabaseManager: {e}", extra={"error": str(e)})
        raise RuntimeError("Application startup failed: Could not connect to database.") from e
    except Exception as e:
        logger.critical(f"Failed during application startup: {e}", extra={"error": str(e)})
        if hasattr(app.state, 'db_manager') and app.state.db_manager:
            logger.info("Attempting to close database connection after startup failure...")
            await app.state.db_manager.close_database_connection()
        raise

    yield

    # Shutdown
    try:
        logger.info("Initiating SSE connection draining...")
        sse_shutdown_manager = get_sse_shutdown_manager()
        sse_shutdown_task = asyncio.create_task(sse_shutdown_manager.initiate_shutdown())

        if hasattr(app.state, "daemonset_task") and app.state.daemonset_task:
            task = app.state.daemonset_task
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                logger.info("Image pre-puller daemonset task cancelled successfully.")

        if hasattr(app.state, "websocket_handler") and app.state.websocket_handler:
            logger.info("Stopping WebSocket event handler...")
            await app.state.websocket_handler.stop()
            logger.info("WebSocket event handler stopped")

        # Close idempotency manager
        logger.info("Closing idempotency manager...")
        await close_idempotency_manager()
        logger.info("Idempotency manager closed")

        # Shutdown health check system
        logger.info("Shutting down health check system...")
        await shutdown_health_checks()
        logger.info("Health check system shut down")

        # Shutdown Kafka metrics
        try:
            kafka_metrics_service = app.state.kafka_metrics_service
            logger.info("Shutting down Kafka metrics collection...")
            await kafka_metrics_service.shutdown()
            logger.info("Kafka metrics collection shut down")
        except AttributeError:
            # Service not initialized, nothing to shutdown
            pass

        # Shutdown user settings service
        if hasattr(app.state, "settings_manager") and app.state.settings_manager:
            logger.info("Shutting down user settings service...")
            await app.state.settings_manager.shutdown()
            logger.info("User settings service shut down")

        # Shutdown notification service
        if hasattr(app.state, "notification_manager") and app.state.notification_manager:
            logger.info("Shutting down notification service...")
            await app.state.notification_manager.shutdown()
            logger.info("Notification service shut down")

        # Shutdown event store consumer
        if hasattr(app.state, "event_store_consumer") and app.state.event_store_consumer:
            logger.info("Shutting down event store consumer...")
            await stop_event_store_consumer()
            logger.info("Event store consumer shut down")

        # Shutdown saga orchestrator
        if hasattr(app.state, "saga_manager") and app.state.saga_manager:
            logger.info("Shutting down saga orchestrator...")
            await app.state.saga_manager.shutdown()
            logger.info("Saga orchestrator shut down")

        # Shutdown projection service
        if hasattr(app.state, "projection_manager") and app.state.projection_manager:
            logger.info("Shutting down projection service...")
            await app.state.projection_manager.shutdown()
            logger.info("Projection service shut down")

        # Shutdown event service
        if hasattr(app.state, "event_service_manager") and app.state.event_service_manager:
            logger.info("Shutting down event service...")
            if hasattr(app.state.event_service_manager, 'close'):
                await app.state.event_service_manager.close()
            logger.info("Event service shut down")

        # Shutdown Kafka producer
        logger.info("Shutting down Kafka producer...")
        await close_producer()
        logger.info("Kafka producer shut down")

        # Shutdown event bus
        if hasattr(app.state, "event_bus_manager") and app.state.event_bus_manager:
            logger.info("Shutting down event bus...")
            await app.state.event_bus_manager.close()
            logger.info("Event bus shut down")

        if hasattr(app.state, "k8s_manager") and app.state.k8s_manager:
            await app.state.k8s_manager.shutdown_all()
            logger.info("All Kubernetes services shut down")

        if hasattr(app.state, "db_manager") and app.state.db_manager:
            logger.info("Closing database connection via DatabaseManager...")
            await app.state.db_manager.close_database_connection()

        # Wait for SSE shutdown to complete
        if 'sse_shutdown_task' in locals():
            logger.info("Waiting for SSE shutdown to complete...")
            try:
                await asyncio.wait_for(sse_shutdown_task, timeout=45.0)
                logger.info("SSE shutdown completed")
            except asyncio.TimeoutError:
                logger.error("SSE shutdown timed out after 45 seconds")

            # Log final SSE shutdown status
            shutdown_status = sse_shutdown_manager.get_shutdown_status()
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
