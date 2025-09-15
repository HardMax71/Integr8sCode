import pytest

from app.core.database_context import AsyncDatabaseConnection, ContextualDatabaseProvider, DatabaseNotInitializedError
from motor.motor_asyncio import AsyncIOMotorDatabase


@pytest.mark.asyncio
async def test_database_connection_from_di(scope) -> None:  # type: ignore[valid-type]
    # Resolve both the raw connection and the database via DI
    conn: AsyncDatabaseConnection = await scope.get(AsyncDatabaseConnection)
    db: AsyncIOMotorDatabase = await scope.get(AsyncIOMotorDatabase)

    assert conn.is_connected() is True
    assert db.name and isinstance(db.name, str)


def test_contextual_provider_requires_set() -> None:
    provider = ContextualDatabaseProvider()
    assert provider.is_initialized() is False
    with pytest.raises(DatabaseNotInitializedError):
        _ = provider.client
