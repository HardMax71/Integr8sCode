from contextlib import asynccontextmanager

from app.api.routes import execution, health, auth
from app.config import get_settings
from app.core.exceptions import configure_exception_handlers
from app.db.mongodb import close_mongo_connection
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    settings = get_settings()
    app.state.mongodb_client = AsyncIOMotorClient(settings.MONGODB_URL)
    app.state.db = app.state.mongodb_client[settings.PROJECT_NAME]
    yield
    # Shutdown
    await close_mongo_connection(app.state.mongodb_client)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router, prefix=settings.API_V1_STR)
    app.include_router(execution.router, prefix=settings.API_V1_STR)
    app.include_router(health.router, prefix=settings.API_V1_STR)

    configure_exception_handlers(app)

    return app


app = create_app()

if __name__ == "__main__":
    import urllib3

    # TODO: Remove this when the issue is fixed
    """
    Example warning:
    app-1    |   warnings.warn(
    app-1    | /usr/local/lib/python3.9/site-packages/urllib3/connectionpool.py:1099: InsecureRequestWarning: 
    Unverified HTTPS request is being made to host 'kubernetes.docker.internal'. Adding certificate verification is strongly advised. 
    See: https://urllib3.readthedocs.io/en/latest/advanced-usage.html#tls-warnings
    """
    urllib3.disable_warnings()

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)