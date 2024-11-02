from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.config import get_settings


def get_database() -> AsyncIOMotorDatabase:
    settings = get_settings()
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    return client[settings.PROJECT_NAME]


async def close_mongo_connection(client: AsyncIOMotorClient):
    client.close()
