import asyncio
import contextlib
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from app.api.routes import auth, execution, health, saved_scripts
from app.config import Settings, get_settings
from app.core.exceptions import configure_exception_handlers
from app.core.logging import logger
from app.core.middleware import RequestSizeLimitMiddleware
from app.db.mongodb import DatabaseManager
from app.services.kubernetes_service import KubernetesService, KubernetesServiceManager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address


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
        if hasattr(app.state, "daemonset_task") and app.state.daemonset_task:
            task = app.state.daemonset_task
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                logger.info("Image pre-puller daemonset task cancelled successfully.")

        if hasattr(app.state, "k8s_manager") and app.state.k8s_manager:
            await app.state.k8s_manager.shutdown_all()
            logger.info("All Kubernetes services shut down")

        if hasattr(app.state, "db_manager") and app.state.db_manager:
            logger.info("Closing database connection via DatabaseManager...")
            await app.state.db_manager.close_database_connection()

    except Exception as e:
        logger.error("Error during application shutdown", extra={"error": str(e)})


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

    app.add_middleware(RequestSizeLimitMiddleware)

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
        ],
        expose_headers=["Content-Length", "Content-Range"],
    )
    logger.info("CORS middleware configured")

    app.add_middleware(SlowAPIMiddleware)

    app.include_router(auth.router, prefix=settings.API_V1_STR)
    app.include_router(execution.router, prefix=settings.API_V1_STR)
    app.include_router(health.router, prefix=settings.API_V1_STR)
    app.include_router(saved_scripts.router, prefix=settings.API_V1_STR)
    logger.info("All routers configured")

    configure_exception_handlers(app)
    logger.info("Exception handlers configured")

    # Initialize Prometheus metrics
    Instrumentator().instrument(app).expose(app)
    logger.info("Prometheus instrumentator configured")

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

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
