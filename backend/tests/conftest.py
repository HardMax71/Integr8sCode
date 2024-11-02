# tests/conftest.py
import os
import pytest
import asyncio
from typing import AsyncGenerator
from fastapi import FastAPI
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from app.main import create_app
from app.config import Settings, get_settings


def get_test_settings() -> Settings:
    return Settings(
        PROJECT_NAME="Integr8sCode_test",
        MONGODB_URL="mongodb://localhost:27017",
        SECRET_KEY="test_secret_key",
        TESTING=True,
    )


@pytest.fixture(scope="session")
def event_loop():
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
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.PROJECT_NAME]
    yield db
    await client.drop_database(settings.PROJECT_NAME)
    client.close()
