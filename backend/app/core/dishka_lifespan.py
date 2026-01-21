from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from beanie import init_beanie
from fastapi import FastAPI
from pymongo.asynchronous.mongo_client import AsyncMongoClient

from app.db.docs import ALL_DOCUMENTS
from app.settings import Settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    container = app.state.dishka_container
    settings = await container.get(Settings)

    client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(
        settings.MONGODB_URL, tz_aware=True, serverSelectionTimeoutMS=5000
    )
    await init_beanie(database=client[settings.DATABASE_NAME], document_models=ALL_DOCUMENTS)

    yield

    await client.close()
    await container.close()
