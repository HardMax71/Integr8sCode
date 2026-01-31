import uvicorn
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    auth,
    dlq,
    events,
    execution,
    grafana_alerts,
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
    settings_router as admin_settings_router,
)
from app.api.routes.admin import (
    users_router as admin_users_router,
)
from app.core.container import create_app_container
from app.core.correlation import CorrelationMiddleware
from app.core.dishka_lifespan import lifespan
from app.core.exceptions import configure_exception_handlers
from app.core.logging import setup_logger
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
    """
    settings = settings or Settings()
    logger = setup_logger(settings.LOG_LEVEL)

    # Note: Metrics are now provided via DI (MetricsProvider) and injected into services.
    # No manual MetricsContext initialization is needed.

    # Disable OpenAPI/Docs in production for security; health endpoints provide readiness
    app = FastAPI(
        title=settings.PROJECT_NAME,
        lifespan=lifespan,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    container = create_app_container(settings)
    setup_dishka(container, app)

    setup_metrics(settings, logger)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(CSRFMiddleware, container=container)
    app.add_middleware(CorrelationMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(CacheControlMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://localhost:5001",
            "https://127.0.0.1:5001",
            "https://[::1]:5001",
            "https://localhost",
            "https://127.0.0.1",
            "https://localhost:443",
            "https://127.0.0.1:443",
            "https://[::1]:443",
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

    app.include_router(auth.router, prefix=settings.API_V1_STR)
    app.include_router(execution.router, prefix=settings.API_V1_STR)
    app.include_router(saved_scripts.router, prefix=settings.API_V1_STR)
    app.include_router(replay.router, prefix=settings.API_V1_STR)
    # Lightweight health endpoints for liveness/readiness
    app.include_router(health.router, prefix=settings.API_V1_STR)
    app.include_router(dlq.router, prefix=settings.API_V1_STR)
    app.include_router(sse.router, prefix=settings.API_V1_STR)
    app.include_router(events.router, prefix=settings.API_V1_STR)
    app.include_router(admin_events_router, prefix=settings.API_V1_STR)
    app.include_router(admin_settings_router, prefix=settings.API_V1_STR)
    app.include_router(admin_users_router, prefix=settings.API_V1_STR)
    app.include_router(user_settings.router, prefix=settings.API_V1_STR)
    app.include_router(notifications.router, prefix=settings.API_V1_STR)
    app.include_router(saga.router, prefix=settings.API_V1_STR)
    app.include_router(grafana_alerts.router, prefix=settings.API_V1_STR)

    # No additional testing-only routes here

    logger.info("All routers configured")

    configure_exception_handlers(app)
    logger.info("Exception handlers configured")

    return app


if __name__ == "__main__":
    settings = Settings()
    logger = setup_logger(settings.LOG_LEVEL)
    logger.info(
        "Starting uvicorn server",
        extra={
            "host": settings.SERVER_HOST,
            "port": settings.SERVER_PORT,
            "ssl_enabled": True,
            "workers": settings.WEB_CONCURRENCY,
            "backlog": settings.WEB_BACKLOG,
            "timeout_keep_alive": settings.WEB_TIMEOUT,
        },
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
