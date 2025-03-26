# tests/conftest.py
import asyncio
from asyncio import AbstractEventLoop
from typing import AsyncGenerator, Generator

import pytest
from app.config import Settings
from app.main import create_app
from fastapi import FastAPI
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient


def get_test_settings() -> Settings:
    return Settings(
        PROJECT_NAME="Integr8sCode_test",
        MONGODB_URL="mongodb://localhost:27017",
        SECRET_KEY="test_secret_key",
        TESTING=True,
    )


@pytest.fixture(scope="session")
def event_loop() -> Generator[AbstractEventLoop, None, None]:
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def app() -> AsyncGenerator[FastAPI, None]:
    app = create_app()
    yield app


@pytest.fixture(scope="session")
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


@pytest.fixture(scope="function")
async def db() -> AsyncGenerator:
    settings = get_test_settings()
    client: AsyncIOMotorClient = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.PROJECT_NAME]
    yield db
    await client.drop_database(settings.PROJECT_NAME)
    client.close()
