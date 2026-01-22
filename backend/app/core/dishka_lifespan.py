import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from beanie import init_beanie
from fastapi import FastAPI
from pymongo.asynchronous.mongo_client import AsyncMongoClient

from app.db.docs import ALL_DOCUMENTS
from app.services.notification_service import NotificationService
from app.settings import Settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    container = app.state.dishka_container
    settings = await container.get(Settings)
    logger = await container.get(logging.Logger)

    client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(
        settings.MONGODB_URL, tz_aware=True, serverSelectionTimeoutMS=5000
    )
    await init_beanie(database=client[settings.DATABASE_NAME], document_models=ALL_DOCUMENTS)

    # Start notification service background tasks
    notification_service = await container.get(NotificationService)

    async def pending_notification_task() -> None:
        """Process pending notifications every 5 seconds."""
        while True:
            try:
                await asyncio.sleep(5)
                await notification_service.process_pending_batch()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error processing pending notifications")

    async def cleanup_notification_task() -> None:
        """Cleanup old notifications every 24 hours."""
        while True:
            try:
                await asyncio.sleep(86400)  # 24 hours
                await notification_service.cleanup_old()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error cleaning up notifications")

    pending_task = asyncio.create_task(pending_notification_task())
    cleanup_task = asyncio.create_task(cleanup_notification_task())
    logger.info("NotificationService background tasks started")

    yield

    # Shutdown background tasks
    pending_task.cancel()
    cleanup_task.cancel()
    try:
        await asyncio.gather(pending_task, cleanup_task)
    except asyncio.CancelledError:
        pass
    logger.info("NotificationService background tasks stopped")

    await client.close()
    await container.close()
