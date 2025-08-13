import asyncio
from typing import Optional

from fastapi import Request
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import Settings
from app.core.logging import logger

__all__ = ["DatabaseManager", "get_database_manager", "get_database", "AsyncIOMotorDatabase"]


class DatabaseManager:
    """Manages the MongoDB client and database connection."""
    client: Optional[AsyncIOMotorClient]
    db: Optional[AsyncIOMotorDatabase]

    def __init__(self, settings: Settings):
        self.settings = settings
        self.db_name = settings.PROJECT_NAME + "_test" if settings.TESTING else settings.PROJECT_NAME
        self.client = None
        self.db = None

    async def connect_to_database(self, retries: int = 5, retry_delay: int = 3) -> None:
        logger.info("Initializing MongoDB connection...")
        temp_client: Optional[AsyncIOMotorClient] = None
        for attempt in range(retries):
            try:
                logger.info(f"Attempting MongoDB connection (Attempt {attempt + 1}/{retries})...")
                temp_client = AsyncIOMotorClient(
                    self.settings.MONGODB_URL,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000,
                    maxPoolSize=50,
                    retryWrites=True,
                    waitQueueTimeoutMS=2500,
                    uuidRepresentation='standard',
                    tz_aware=True
                )
                # Test the connection
                await temp_client.admin.command("ping")
                self.client = temp_client
                self.db = self.client[self.db_name]
                logger.info(
                    f"Successfully connected to MongoDB and got DB handle '{self.db_name}'",
                    extra={"attempt": attempt + 1}
                )
                return  # Success
            except Exception as e:
                if temp_client:
                    temp_client.close()

                if attempt == retries - 1:
                    logger.critical(
                        "Failed to connect to MongoDB after all retries.",
                        extra={"attempt": attempt + 1, "max_retries": retries, "error": str(e)},
                    )
                    raise ConnectionError(f"Could not connect to MongoDB: {e}") from e

                logger.warning(
                    "MongoDB connection attempt failed, retrying...",
                    extra={"attempt": attempt + 1, "retry_delay": retry_delay, "error": str(e)},
                )
                await asyncio.sleep(retry_delay)
        # Should not be reached if retries > 0
        raise ConnectionError("MongoDB initialization failed unexpectedly.")

    async def close_database_connection(self) -> None:
        """Closes the MongoDB connection."""
        logger.info("Closing MongoDB connection...")
        if self.client:
            try:
                self.client.close()
                logger.info("MongoDB connection closed successfully.")
                self.client = None
                self.db = None
            except Exception as e:
                logger.error("Error closing MongoDB connection", extra={"error": str(e)})
        else:
            logger.info("MongoDB connection already closed or never initialized.")

    def get_database(self) -> AsyncIOMotorDatabase:
        """Returns the database handle. Raises Exception if not connected."""
        if self.db is None:
            logger.error("Attempted to get database handle before connection was established.")
            raise RuntimeError("Database is not connected.")
        return self.db


def get_database_manager(request: Request) -> DatabaseManager:
    """FastAPI dependency to get the database manager from app state"""
    manager: DatabaseManager = request.app.state.db_manager
    return manager


def get_database(request: Request) -> AsyncIOMotorDatabase:
    """FastAPI dependency to get the database from app state"""
    db_manager: DatabaseManager = request.app.state.db_manager
    return db_manager.get_database()
