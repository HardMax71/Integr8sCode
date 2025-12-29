import contextvars
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncContextManager, Protocol, TypeVar, runtime_checkable

from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.cursor import AsyncCursor
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.asynchronous.mongo_client import AsyncMongoClient
from pymongo.errors import ServerSelectionTimeoutError

# Python 3.12 type aliases using the new 'type' statement
# MongoDocument represents the raw document type returned by PyMongo operations
type MongoDocument = dict[str, Any]
type DBClient = AsyncMongoClient[MongoDocument]
type Database = AsyncDatabase[MongoDocument]
type Collection = AsyncCollection[MongoDocument]
type Cursor = AsyncCursor[MongoDocument]
type DBSession = AsyncClientSession

# Type variable for generic database provider
T = TypeVar("T")


class DatabaseError(Exception):
    pass


class DatabaseNotInitializedError(DatabaseError):
    """Raised when attempting to use database before initialization."""

    pass


class DatabaseAlreadyInitializedError(DatabaseError):
    """Raised when attempting to initialize an already initialized database."""

    pass


@dataclass(frozen=True)
class DatabaseConfig:
    mongodb_url: str
    db_name: str
    server_selection_timeout_ms: int = 5000
    connect_timeout_ms: int = 10000
    max_pool_size: int = 100
    min_pool_size: int = 10
    retry_writes: bool = True
    retry_reads: bool = True
    write_concern: str = "majority"
    journal: bool = True


@runtime_checkable
class DatabaseProvider(Protocol):
    @property
    def client(self) -> DBClient:
        """Get the MongoDB client."""
        ...

    @property
    def database(self) -> Database:
        """Get the database instance."""
        ...

    @property
    def db_name(self) -> str:
        """Get the database name."""
        ...

    def is_initialized(self) -> bool:
        """Check if the provider is initialized."""
        ...

    def session(self) -> AsyncContextManager[DBSession]:
        """Create a database session for transactions."""
        ...


class AsyncDatabaseConnection:
    __slots__ = ("_client", "_database", "_db_name", "_config", "logger")

    def __init__(self, config: DatabaseConfig, logger: logging.Logger) -> None:
        self._config = config
        self._client: DBClient | None = None
        self._database: Database | None = None
        self._db_name: str = config.db_name
        self.logger = logger

    async def connect(self) -> None:
        """
        Establish connection to MongoDB.

        Raises:
            DatabaseAlreadyInitializedError: If already connected
            ServerSelectionTimeoutError: If cannot connect to MongoDB
        """
        if self._client is not None:
            raise DatabaseAlreadyInitializedError("Connection already established")

        self.logger.info(f"Connecting to MongoDB database: {self._db_name}")

        # PyMongo Async automatically uses the current event loop
        client: DBClient = AsyncMongoClient(
            self._config.mongodb_url,
            serverSelectionTimeoutMS=self._config.server_selection_timeout_ms,
            connectTimeoutMS=self._config.connect_timeout_ms,
            maxPoolSize=self._config.max_pool_size,
            minPoolSize=self._config.min_pool_size,
            retryWrites=self._config.retry_writes,
            retryReads=self._config.retry_reads,
            w=self._config.write_concern,
            journal=self._config.journal,
        )

        # Verify connection
        try:
            await client.admin.command("ping")
            self.logger.info("Successfully connected to MongoDB")
        except ServerSelectionTimeoutError as e:
            self.logger.error(f"Failed to connect to MongoDB: {e}")
            await client.close()
            raise

        self._client = client
        self._database = client[self._db_name]

    async def disconnect(self) -> None:
        if self._client is not None:
            self.logger.info("Closing MongoDB connection")
            await self._client.close()
            self._client = None
            self._database = None

    @property
    def client(self) -> DBClient:
        if self._client is None:
            raise DatabaseNotInitializedError("Database connection not established")
        return self._client

    @property
    def database(self) -> Database:
        if self._database is None:
            raise DatabaseNotInitializedError("Database connection not established")
        return self._database

    @property
    def db_name(self) -> str:
        return self._db_name

    def is_connected(self) -> bool:
        return self._client is not None

    @asynccontextmanager
    async def session(self) -> AsyncIterator[DBSession]:
        """
        Create a database session for transactions.

        Yields:
            Database session for use in transactions

        Example:
            async with connection.session() as session:
                await collection.insert_one(doc, session=session)
        """
        async with self.client.start_session() as session:
            async with await session.start_transaction():
                yield session


class ContextualDatabaseProvider(DatabaseProvider):
    def __init__(self) -> None:
        self._connection_var: contextvars.ContextVar[AsyncDatabaseConnection | None] = contextvars.ContextVar(
            "db_connection", default=None
        )

    def set_connection(self, connection: AsyncDatabaseConnection) -> None:
        self._connection_var.set(connection)

    def clear_connection(self) -> None:
        self._connection_var.set(None)

    @property
    def _connection(self) -> AsyncDatabaseConnection:
        connection = self._connection_var.get()
        if connection is None:
            raise DatabaseNotInitializedError(
                "No database connection in current context. Ensure connection is set in the request lifecycle."
            )
        return connection

    @property
    def client(self) -> DBClient:
        return self._connection.client

    @property
    def database(self) -> Database:
        return self._connection.database

    @property
    def db_name(self) -> str:
        return self._connection.db_name

    def is_initialized(self) -> bool:
        connection = self._connection_var.get()
        return connection is not None and connection.is_connected()

    def session(self) -> AsyncContextManager[DBSession]:
        return self._connection.session()


class DatabaseConnectionPool:
    def __init__(self, logger: logging.Logger) -> None:
        self._connections: dict[str, AsyncDatabaseConnection] = {}
        self.logger = logger

    async def create_connection(self, key: str, config: DatabaseConfig) -> AsyncDatabaseConnection:
        """
        Create and store a new database connection.

        Args:
            key: Unique identifier for this connection
            config: Database configuration

        Returns:
            The created connection

        Raises:
            DatabaseAlreadyInitializedError: If key already exists
        """
        if key in self._connections:
            raise DatabaseAlreadyInitializedError(f"Connection '{key}' already exists")

        connection = AsyncDatabaseConnection(config, self.logger)
        await connection.connect()
        self._connections[key] = connection
        return connection

    def get_connection(self, key: str) -> AsyncDatabaseConnection:
        """
        Get a connection by key.

        Raises:
            KeyError: If connection not found
        """
        return self._connections[key]

    async def close_connection(self, key: str) -> None:
        if key in self._connections:
            await self._connections[key].disconnect()
            del self._connections[key]

    async def close_all(self) -> None:
        for connection in self._connections.values():
            await connection.disconnect()
        self._connections.clear()


# Factory functions for dependency injection
def create_database_connection(config: DatabaseConfig, logger: logging.Logger) -> AsyncDatabaseConnection:
    return AsyncDatabaseConnection(config, logger)


def create_contextual_provider() -> ContextualDatabaseProvider:
    return ContextualDatabaseProvider()


def create_connection_pool(logger: logging.Logger) -> DatabaseConnectionPool:
    return DatabaseConnectionPool(logger)


async def get_database_provider() -> DatabaseProvider:
    raise RuntimeError("Database provider not configured. This dependency should be overridden in app startup.")
