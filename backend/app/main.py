import uvicorn
from dishka.integrations.fastapi import setup_dishka as setup_dishka_fastapi
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    auth,
    execution,
    health,
    notifications,
    replay,
    saga,
    saved_scripts,
    sse,
    user_settings,
)
from app.api.routes.admin import (
    events_router as admin_events_router,
)
from app.api.routes.admin import (
    executions_router as admin_executions_router,
)
from app.api.routes.admin import (
    rate_limits_router as admin_rate_limits_router,
)
from app.api.routes.admin import (
    settings_router as admin_settings_router,
)
from app.api.routes.admin import (
    users_router as admin_users_router,
)
from app.core.container import create_app_container
from app.core.dishka_lifespan import lifespan
from app.core.exceptions import configure_exception_handlers
from app.core.logging import setup_log_exporter, setup_logger
from app.core.middlewares import (
    CacheControlMiddleware,
    CSRFMiddleware,
    MetricsMiddleware,
    RateLimitMiddleware,
    RequestSizeLimitMiddleware,
    setup_metrics,
)
from app.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """
    Create the FastAPI application.

    Args:
        settings: Optional pre-configured settings (e.g., TestSettings for testing).
                 If None, loads from config.toml.

    Note: DI container and infrastructure (MongoDB, Kafka) are created in the
    async lifespan handler to allow proper async initialization (init_beanie).
    """
    settings = settings or Settings()
    logger = setup_logger(settings.LOG_LEVEL)

    # Disable OpenAPI/Docs in production for security; health endpoints provide readiness
    app = FastAPI(
        title=settings.PROJECT_NAME,
        lifespan=lifespan,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    # Store settings on app state for lifespan access
    app.state.settings = settings

    # Create DI container and set up Dishka middleware
    # Note: init_beanie() is called in lifespan before any providers are resolved
    container = create_app_container(settings)
    setup_dishka_fastapi(container, app)

    setup_metrics(settings, logger)
    setup_log_exporter(settings, logger)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(CacheControlMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "Origin",
            "X-Requested-With",
            "X-CSRF-Token",
        ],
        expose_headers=["Content-Length", "Content-Range"],
    )
    logger.info("CORS middleware configured", origins=settings.CORS_ORIGINS)

    app.include_router(auth.router, prefix=settings.API_V1_STR)
    app.include_router(execution.router, prefix=settings.API_V1_STR)
    app.include_router(saved_scripts.router, prefix=settings.API_V1_STR)
    app.include_router(replay.router, prefix=settings.API_V1_STR)
    # Lightweight health endpoints for liveness/readiness
    app.include_router(health.router, prefix=settings.API_V1_STR)
    app.include_router(sse.router, prefix=settings.API_V1_STR)
    app.include_router(admin_events_router, prefix=settings.API_V1_STR)
    app.include_router(admin_executions_router, prefix=settings.API_V1_STR)
    app.include_router(admin_rate_limits_router, prefix=settings.API_V1_STR)
    app.include_router(admin_settings_router, prefix=settings.API_V1_STR)
    app.include_router(admin_users_router, prefix=settings.API_V1_STR)
    app.include_router(user_settings.router, prefix=settings.API_V1_STR)
    app.include_router(notifications.router, prefix=settings.API_V1_STR)
    app.include_router(saga.router, prefix=settings.API_V1_STR)

    logger.info("All routers configured")

    configure_exception_handlers(app)
    logger.info("Exception handlers configured")

    return app


if __name__ == "__main__":
    settings = Settings()
    logger = setup_logger(settings.LOG_LEVEL)
    logger.info(
        "Starting uvicorn server",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        ssl_enabled=True,
        workers=settings.WEB_CONCURRENCY,
        backlog=settings.WEB_BACKLOG,
        timeout_keep_alive=settings.WEB_TIMEOUT,
    )
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        ssl_keyfile=settings.SSL_KEYFILE,
        ssl_certfile=settings.SSL_CERTFILE,
        workers=settings.WEB_CONCURRENCY,
        backlog=settings.WEB_BACKLOG,
        timeout_keep_alive=settings.WEB_TIMEOUT,
    )
