import redis.asyncio as redis
from app.db.docs import ALL_DOCUMENTS


async def cleanup_db_and_redis(redis_client: redis.Redis) -> None:
    """Clean DB and Redis before a test.

    Beanie is already initialized once during app lifespan (dishka_lifespan.py).
    We just delete documents to preserve indexes and avoid file descriptor exhaustion.

    NOTE: With pytest-xdist, each worker is assigned a dedicated Redis DB
    derived from the worker id (sum(_WORKER_ID.encode()) % 16), so flushdb()
    is safe and only affects that worker's database. See tests/conftest.py
    for REDIS_DB setup.
    """
    for doc_class in ALL_DOCUMENTS:
        await doc_class.delete_all()

    await redis_client.flushdb()
