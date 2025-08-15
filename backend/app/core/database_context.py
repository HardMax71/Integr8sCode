"""
Database connection management with proper dependency injection.
This module provides async-safe database access using modern patterns.
"""
from __future__ import annotations

import contextvars
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncContextManager, AsyncIterator, Protocol, TypeVar, runtime_checkable

from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorClientSession, AsyncIOMotorDatabase
from pymongo.errors import ServerSelectionTimeoutError

from app.core.logging import logger

# Python 3.12 type aliases
type DBClient = AsyncIOMotorClient[Any]
type Database = AsyncIOMotorDatabase[Any]
type DBSession = AsyncIOMotorClientSession

# Type variable for generic database provider
T = TypeVar('T')


class DatabaseError(Exception):
    """Base exception for database-related errors."""
    pass


class DatabaseNotInitializedError(DatabaseError):
    """Raised when attempting to use database before initialization."""
    pass


class DatabaseAlreadyInitializedError(DatabaseError):
    """Raised when attempting to initialize an already initialized database."""
    pass


@dataclass(frozen=True)
class DatabaseConfig:
    """Immutable database configuration."""
    mongodb_url: str
    db_name: str
    server_selection_timeout_ms: int = 5000
    connect_timeout_ms: int = 10000
    max_pool_size: int = 100
    min_pool_size: int = 10
    retry_writes: bool = True
    retry_reads: bool = True
    write_concern: str = 'majority'
    journal: bool = True


@runtime_checkable
class DatabaseProvider(Protocol):
    """Protocol for database providers."""

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
    """
    Manages a single MongoDB connection instance.
    
    This class is responsible only for connection lifecycle management.
    It does not handle context or global state.
    """

    __slots__ = ('_client', '_database', '_db_name', '_config')

    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config
        self._client: DBClient | None = None
        self._database: Database | None = None
        self._db_name: str = config.db_name

    async def connect(self) -> None:
        """
        Establish connection to MongoDB.
        
        Raises:
            DatabaseAlreadyInitializedError: If already connected
            ServerSelectionTimeoutError: If cannot connect to MongoDB
        """
        if self._client is not None:
            raise DatabaseAlreadyInitializedError("Connection already established")

        logger.info(f"Connecting to MongoDB database: {self._db_name}")

        # Create client with configuration
        client: AsyncIOMotorClient = AsyncIOMotorClient(
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
            await client.admin.command('ping')
            logger.info("Successfully connected to MongoDB")
        except ServerSelectionTimeoutError as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            client.close()
            raise

        self._client = client
        self._database = client[self._db_name]

    async def disconnect(self) -> None:
        """Close the database connection gracefully."""
        if self._client is not None:
            logger.info("Closing MongoDB connection")
            self._client.close()
            self._client = None
            self._database = None

    @property
    def client(self) -> DBClient:
        """Get the MongoDB client."""
        if self._client is None:
            raise DatabaseNotInitializedError("Database connection not established")
        return self._client

    @property
    def database(self) -> Database:
        """Get the database instance."""
        if self._database is None:
            raise DatabaseNotInitializedError("Database connection not established")
        return self._database

    @property
    def db_name(self) -> str:
        """Get the database name."""
        return self._db_name

    def is_connected(self) -> bool:
        """Check if connected to database."""
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
        async with await self.client.start_session() as session:
            async with session.start_transaction():
                yield session


class ContextualDatabaseProvider(DatabaseProvider):
    """
    Provides database access using contextvars for async isolation.
    
    This implementation uses contextvars to provide isolated database
    access per async context (request).
    """

    def __init__(self) -> None:
        # Context variable to store connection per async context
        self._connection_var: contextvars.ContextVar[AsyncDatabaseConnection | None] = \
            contextvars.ContextVar('db_connection', default=None)

    def set_connection(self, connection: AsyncDatabaseConnection) -> None:
        """Set the database connection for the current context."""
        self._connection_var.set(connection)

    def clear_connection(self) -> None:
        """Clear the database connection from the current context."""
        self._connection_var.set(None)

    @property
    def _connection(self) -> AsyncDatabaseConnection:
        """Get the current connection or raise error."""
        connection = self._connection_var.get()
        if connection is None:
            raise DatabaseNotInitializedError(
                "No database connection in current context. "
                "Ensure connection is set in the request lifecycle."
            )
        return connection

    @property
    def client(self) -> DBClient:
        """Get the MongoDB client from current context."""
        return self._connection.client

    @property
    def database(self) -> Database:
        """Get the database from current context."""
        return self._connection.database

    @property
    def db_name(self) -> str:
        """Get the database name from current context."""
        return self._connection.db_name

    def is_initialized(self) -> bool:
        """Check if database is available in current context."""
        connection = self._connection_var.get()
        return connection is not None and connection.is_connected()

    def session(self) -> AsyncContextManager[DBSession]:
        """Create a database session for transactions."""
        return self._connection.session()


class DatabaseConnectionPool:
    """
    Manages a pool of database connections for different contexts.
    
    This can be used for managing multiple database connections
    (e.g., for different tenants or shards).
    """

    def __init__(self) -> None:
        self._connections: dict[str, AsyncDatabaseConnection] = {}

    async def create_connection(
            self,
            key: str,
            config: DatabaseConfig
    ) -> AsyncDatabaseConnection:
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

        connection = AsyncDatabaseConnection(config)
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
        """Close and remove a specific connection."""
        if key in self._connections:
            await self._connections[key].disconnect()
            del self._connections[key]

    async def close_all(self) -> None:
        """Close all connections in the pool."""
        for connection in self._connections.values():
            await connection.disconnect()
        self._connections.clear()


# Factory functions for dependency injection

def create_database_connection(config: DatabaseConfig) -> AsyncDatabaseConnection:
    """
    Factory function to create a database connection.
    
    This is the primary way to create connections in the application.
    """
    return AsyncDatabaseConnection(config)


def create_contextual_provider() -> ContextualDatabaseProvider:
    """
    Factory function to create a contextual database provider.
    
    This provider uses contextvars for async-safe database access.
    """
    return ContextualDatabaseProvider()


def create_connection_pool() -> DatabaseConnectionPool:
    """
    Factory function to create a connection pool.
    
    Use this for managing multiple database connections.
    """
    return DatabaseConnectionPool()


# Middleware for FastAPI integration

class DatabaseMiddleware:
    """
    FastAPI middleware for database connection management.
    
    This middleware sets up the database connection for each request
    using the contextual provider.
    """

    def __init__(
            self,
            connection: AsyncDatabaseConnection,
            provider: ContextualDatabaseProvider
    ) -> None:
        self.connection = connection
        self.provider = provider

    async def __call__(self, request: Any, call_next: Any) -> Any:
        """Set up database context for the request."""
        # Set connection in context
        self.provider.set_connection(self.connection)

        try:
            # Process request
            response = await call_next(request)
            return response
        finally:
            # Clear context
            self.provider.clear_connection()


# Dependency injection for FastAPI

async def get_database_provider() -> DatabaseProvider:
    """
    FastAPI dependency to get the database provider.
    
    This function will be overridden in the application startup
    to provide the actual database provider instance.
    """
    raise RuntimeError("Database provider not configured. This dependency should be overridden in app startup.")


async def get_database(
        provider: DatabaseProvider = Depends(get_database_provider)
) -> Database:
    """FastAPI dependency to get the database instance."""
    return provider.database


async def get_db_client(
        provider: DatabaseProvider = Depends(get_database_provider)
) -> DBClient:
    """FastAPI dependency to get the MongoDB client."""
    return provider.client


@asynccontextmanager
async def database_transaction(
        provider: DatabaseProvider
) -> AsyncIterator[DBSession]:
    """
    Create a database transaction using the provided database provider.
    
    Args:
        provider: Database provider instance
        
    Yields:
        Database session for transactions
        
    Example:
        async with database_transaction(provider) as session:
            await collection.insert_one(doc, session=session)
    """
    async with provider.session() as session:
        yield session
