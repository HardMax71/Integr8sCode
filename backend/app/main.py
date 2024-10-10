from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient

from app.api.routes import execution, health, auth
from app.core.exceptions import configure_exception_handlers
from app.db.mongodb import get_database, close_mongo_connection
from app.config import get_settings

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