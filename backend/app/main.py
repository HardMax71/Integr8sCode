from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api.routes import auth, execution, health, saved_scripts
from app.config import get_settings
from app.core.exceptions import configure_exception_handlers
from app.core.logging import logger
from app.core.middleware import RequestSizeLimitMiddleware
from app.db.mongodb import close_mongo_connection, init_mongodb
from app.services.kubernetes_service import KubernetesServiceManager

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup
    settings = get_settings()
    logger.info(
        "Starting application",
        extra={
            "project_name": settings.PROJECT_NAME,
            "environment": "test" if settings.TESTING else "production",
        },
    )

    try:
        # Initialize MongoDB with retries
        app.state.mongodb_client = await init_mongodb()
        if app.state.mongodb_client is not None:
            app.state.db = app.state.mongodb_client[settings.PROJECT_NAME]
        logger.info("MongoDB initialization completed")

        # Initialize K8s manager
        app.state.k8s_manager = KubernetesServiceManager()
        logger.info("Kubernetes service manager initialized")
    except Exception as e:
        logger.critical("Failed to initialize MongoDB", extra={"error": str(e)})
        raise

    yield

    # Shutdown
    try:
        # Shutdown all K8s services first
        if hasattr(app.state, "k8s_manager"):
            await app.state.k8s_manager.shutdown_all()
            logger.info("All Kubernetes services shut down")

        # Then close MongoDB connection
        if hasattr(app.state, "mongodb_client") and app.state.mongodb_client is not None:
            await close_mongo_connection(app.state.mongodb_client)
    except Exception as e:
        logger.error("Error during application shutdown", extra={"error": str(e)})


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

    if settings.TESTING:
        logger.info("Running in test mode")
        app.state.mongodb_client = AsyncIOMotorClient(settings.MONGODB_URL)
        app.state.db = app.state.mongodb_client[settings.PROJECT_NAME + "_test"]

    app.add_middleware(RequestSizeLimitMiddleware)

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

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    logger.info(
        "Starting uvicorn server",
        extra={"host": "0.0.0.0", "port": 443, "ssl_enabled": True},
    )
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=443,
        ssl_keyfile="/app/certs/server.key",
        ssl_certfile="/app/certs/server.crt",
    )
