from contextlib import asynccontextmanager

from app.api.routes import execution, health, auth, saved_scripts
from app.config import get_settings
from app.core.exceptions import configure_exception_handlers
from app.core.logging import logger  # Import logger from the new location
from app.db.mongodb import close_mongo_connection
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])


@asynccontextmanager
async def lifespan(app: FastAPI):
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
        app.state.mongodb_client = AsyncIOMotorClient(settings.MONGODB_URL)
        app.state.db = app.state.mongodb_client[settings.PROJECT_NAME]
        logger.info("Successfully connected to MongoDB")
    except Exception as e:
        logger.error("Failed to connect to MongoDB", extra={"error": str(e)})
        raise

    yield

    # Shutdown
    try:
        await close_mongo_connection(app.state.mongodb_client)
        logger.info("Successfully closed MongoDB connection")
    except Exception as e:
        logger.error("Error closing MongoDB connection", extra={"error": str(e)})


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

    if settings.TESTING:
        logger.info("Running in test mode")
        app.state.mongodb_client = AsyncIOMotorClient(settings.MONGODB_URL)
        app.state.db = app.state.mongodb_client[settings.PROJECT_NAME + "_test"]

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://localhost:5001",
            "https://127.0.0.1:5001",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
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
