"""Test cleanup utilities.

Tests use unique IDs (UUIDs) for all entities, so they don't conflict with each other.
No database-wide cleanup is needed - tests are isolated by their unique identifiers.
"""

import redis.asyncio as redis
from app.core.database_context import Database


async def cleanup_db_and_redis(db: Database, redis_client: redis.Redis) -> None:
    """No-op cleanup - tests use unique IDs and don't need database isolation.

    Tests create entities with unique identifiers:
      - Users: test_user_{uuid}@example.com
      - Executions: UUID-based execution_id
      - Events: UUID-based event_id
      - etc.

    Each test only interacts with its own data (filtered by user_id or entity IDs),
    so parallel execution is safe without destructive cleanup.

    This function is kept for backwards compatibility but does nothing.
    Database hygiene (removing stale test data) can be done periodically outside tests.
    """
    # Intentionally empty - no cleanup needed
    pass
