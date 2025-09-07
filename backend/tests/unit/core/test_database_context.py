import pytest

from app.core.database_context import (
    AsyncDatabaseConnection,
    ContextualDatabaseProvider,
    DatabaseAlreadyInitializedError,
    DatabaseConfig,
    DatabaseNotInitializedError,
)


class Admin:
    async def command(self, cmd):  # noqa: ANN001
        return {"ok": 1}


class Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    def start_transaction(self):
        return self


class Client:
    def __init__(self, url, **kwargs):  # noqa: ANN001
        self._dbs = {}
        self.admin = Admin()
        self.closed = False

    def __getitem__(self, name):  # noqa: ANN001
        self._dbs.setdefault(name, {"name": name})
        return self._dbs[name]

    def close(self):
        self.closed = True

    async def start_session(self):
        return Session()


@pytest.mark.asyncio
async def test_async_database_connection_connect_disconnect(monkeypatch):
    # Patch motor client ctor to our stub
    import app.core.database_context as dc

    monkeypatch.setattr(dc, "AsyncIOMotorClient", Client)

    cfg = DatabaseConfig(mongodb_url="mongodb://x", db_name="db")
    conn = AsyncDatabaseConnection(cfg)

    await conn.connect()
    assert conn.is_connected()
    assert conn.db_name == "db"
    assert conn.database["name"] == "db"

    # Session context manager works
    async with conn.session() as s:
        assert isinstance(s, Session)

    await conn.disconnect()
    assert not conn.is_connected()


@pytest.mark.asyncio
async def test_contextual_provider_requires_set():
    provider = ContextualDatabaseProvider()
    # is_initialized() returns False when not set, doesn't raise
    assert provider.is_initialized() is False
    
    # Accessing properties that require connection should raise
    with pytest.raises(DatabaseNotInitializedError):
        _ = provider.client

