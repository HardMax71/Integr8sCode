import asyncio
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings
from app.core.logging import logger


async def init_mongodb(retries: int = 3, retry_delay: int = 5) -> Optional[AsyncIOMotorClient]:
    settings = get_settings()

    for attempt in range(retries):
        try:
            client: AsyncIOMotorClient = AsyncIOMotorClient(
                settings.MONGODB_URL,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
                maxPoolSize=50,
                retryWrites=True,
                waitQueueTimeoutMS=2500,
            )
            # Test the connection
            await client.admin.command("ping")
            logger.info(
                "Successfully connected to MongoDB", extra={"attempt": attempt + 1}
            )
            return client
        except Exception as e:
            if attempt == retries - 1:
                logger.critical(
                    "Failed to connect to MongoDB",
                    extra={
                        "attempt": attempt + 1,
                        "max_retries": retries,
                        "error": str(e),
                    },
                )
                raise
            logger.warning(
                "MongoDB connection attempt failed, retrying...",
                extra={
                    "attempt": attempt + 1,
                    "retry_delay": retry_delay,
                    "error": str(e),
                },
            )
            await asyncio.sleep(retry_delay)

    return None


def get_database() -> AsyncIOMotorDatabase:
    settings = get_settings()
    client: AsyncIOMotorClient = AsyncIOMotorClient(
        settings.MONGODB_URL,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        maxPoolSize=50,
        retryWrites=True,
        waitQueueTimeoutMS=2500,
    )
    return client[settings.PROJECT_NAME]


async def close_mongo_connection(client: AsyncIOMotorClient) -> None:
    try:
        client.close()
        logger.info("MongoDB connection closed successfully")
    except Exception as e:
        logger.error("Error closing MongoDB connection", extra={"error": str(e)})
