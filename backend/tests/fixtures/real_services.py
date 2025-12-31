"""
Real service fixtures for integration testing.
Uses actual MongoDB, Redis, Kafka from docker-compose instead of mocks.
"""
import asyncio
import uuid
from typing import AsyncGenerator, Optional, Dict, Any
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
import redis.asyncio as redis
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError
from pymongo.asynchronous.mongo_client import AsyncMongoClient

from app.core.database_context import Database, DBClient
from app.settings import Settings


class TestServiceConnections:
    """Manages connections to real services for testing."""

    def __init__(self, test_id: str):
        self.test_id = test_id
        self.mongo_client: Optional[DBClient] = None
        self.redis_client: Optional[redis.Redis] = None
        self.kafka_producer: Optional[AIOKafkaProducer] = None
        self.kafka_consumer: Optional[AIOKafkaConsumer] = None
        self.db_name = f"test_{test_id}"

    async def connect_mongodb(self, url: str) -> Database:
        """Connect to MongoDB and return test-specific database."""
        self.mongo_client = AsyncMongoClient(
            url,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            maxPoolSize=10
        )
        # Verify connection
        await self.mongo_client.admin.command("ping")
        return self.mongo_client[self.db_name]
    
    async def connect_redis(self, host: str = "localhost", port: int = 6379, db: int = 1) -> redis.Redis:
        """Connect to Redis using test database (db=1)."""
        self.redis_client = redis.Redis(
            host=host,
            port=port,
            db=db,  # Use db 1 for tests, 0 for production
            decode_responses=True,
            max_connections=10,
            socket_connect_timeout=5,
            socket_timeout=5
        )
        # Verify connection
        await self.redis_client.execute_command("PING")
        # Clear test namespace
        await self.redis_client.flushdb()
        return self.redis_client
    
    async def connect_kafka_producer(self, bootstrap_servers: str) -> Optional[AIOKafkaProducer]:
        """Connect Kafka producer if available."""
        try:
            self.kafka_producer = AIOKafkaProducer(
                bootstrap_servers=bootstrap_servers,
                compression_type="gzip",
                acks="all",
                enable_idempotence=True,
                max_in_flight_requests_per_connection=5,
                request_timeout_ms=30000,
                metadata_max_age_ms=60000
            )
            await self.kafka_producer.start()
            return self.kafka_producer
        except (KafkaConnectionError, OSError):
            # Kafka not available, tests can still run without it
            return None
    
    async def connect_kafka_consumer(self, bootstrap_servers: str, group_id: str) -> Optional[AIOKafkaConsumer]:
        """Connect Kafka consumer if available."""
        try:
            self.kafka_consumer = AIOKafkaConsumer(
                bootstrap_servers=bootstrap_servers,
                group_id=group_id,
                auto_offset_reset="earliest",
                enable_auto_commit=False,
                max_poll_records=100,
                session_timeout_ms=30000,
                heartbeat_interval_ms=10000
            )
            await self.kafka_consumer.start()
            return self.kafka_consumer
        except (KafkaConnectionError, OSError):
            return None
    
    async def cleanup(self):
        """Clean up all connections and test data."""
        # Drop test MongoDB database
        if self.mongo_client:
            await self.mongo_client.drop_database(self.db_name)
            await self.mongo_client.close()
        
        # Clear Redis test database
        if self.redis_client:
            await self.redis_client.flushdb()
            await self.redis_client.aclose()
        
        # Close Kafka connections
        if self.kafka_producer:
            await self.kafka_producer.stop()
        if self.kafka_consumer:
            await self.kafka_consumer.stop()


@pytest_asyncio.fixture
async def real_services(request) -> AsyncGenerator[TestServiceConnections, None]:
    """
    Provides real service connections for testing.
    Each test gets its own isolated database.
    """
    # Generate unique test ID
    test_id = f"{request.node.name}_{uuid.uuid4().hex[:8]}"
    test_id = test_id.replace("[", "_").replace("]", "_").replace("-", "_")
    
    connections = TestServiceConnections(test_id)
    
    yield connections
    
    # Cleanup after test
    await connections.cleanup()


@pytest_asyncio.fixture
async def real_mongodb(real_services: TestServiceConnections) -> Database:
    """Get real MongoDB database for testing."""
    # Use MongoDB from docker-compose with auth
    return await real_services.connect_mongodb(
        "mongodb://root:rootpassword@localhost:27017"
    )


@pytest_asyncio.fixture
async def real_redis(real_services: TestServiceConnections) -> redis.Redis:
    """Get real Redis client for testing."""
    return await real_services.connect_redis()


@pytest_asyncio.fixture
async def real_kafka_producer(real_services: TestServiceConnections) -> Optional[AIOKafkaProducer]:
    """Get real Kafka producer if available."""
    return await real_services.connect_kafka_producer("localhost:9092")


@pytest_asyncio.fixture
async def real_kafka_consumer(real_services: TestServiceConnections) -> Optional[AIOKafkaConsumer]:
    """Get real Kafka consumer if available."""
    test_group = f"test_group_{real_services.test_id}"
    return await real_services.connect_kafka_consumer("localhost:9092", test_group)


@asynccontextmanager
async def mongodb_transaction(db: Database):
    """
    Context manager for MongoDB transactions.
    Automatically rolls back on error.
    """
    client = db.client
    async with await client.start_session() as session:
        async with session.start_transaction():
            try:
                yield session
                await session.commit_transaction()
            except Exception:
                await session.abort_transaction()
                raise


@asynccontextmanager
async def redis_pipeline(client: redis.Redis):
    """Context manager for Redis pipeline operations."""
    pipe = client.pipeline()
    try:
        yield pipe
        await pipe.execute()
    except Exception:
        # Redis doesn't support rollback, but we can clear the pipeline
        pipe.reset()
        raise


class TestDataFactory:
    """Factory for creating test data in real services."""

    @staticmethod
    async def create_test_user(db: Database, **kwargs) -> Dict[str, Any]:
        """Create a test user in MongoDB."""
        user_data = {
            "user_id": str(uuid.uuid4()),
            "username": kwargs.get("username", f"testuser_{uuid.uuid4().hex[:8]}"),
            "email": kwargs.get("email", f"test_{uuid.uuid4().hex[:8]}@example.com"),
            "password_hash": "$2b$12$test_hash",  # bcrypt format
            "role": kwargs.get("role", "user"),
            "is_active": kwargs.get("is_active", True),
            "is_superuser": kwargs.get("is_superuser", False),
            "created_at": asyncio.get_event_loop().time(),
            "updated_at": asyncio.get_event_loop().time()
        }
        user_data.update(kwargs)
        
        result = await db.users.insert_one(user_data)
        user_data["_id"] = result.inserted_id
        return user_data
    
    @staticmethod
    async def create_test_execution(db: Database, **kwargs) -> Dict[str, Any]:
        """Create a test execution in MongoDB."""
        execution_data = {
            "execution_id": str(uuid.uuid4()),
            "user_id": kwargs.get("user_id", str(uuid.uuid4())),
            "script": kwargs.get("script", "print('test')"),
            "language": kwargs.get("language", "python"),
            "language_version": kwargs.get("language_version", "3.11"),
            "status": kwargs.get("status", "queued"),
            "created_at": asyncio.get_event_loop().time(),
            "updated_at": asyncio.get_event_loop().time()
        }
        execution_data.update(kwargs)
        
        result = await db.executions.insert_one(execution_data)
        execution_data["_id"] = result.inserted_id
        return execution_data
    
    @staticmethod
    async def create_test_event(db: Database, **kwargs) -> Dict[str, Any]:
        """Create a test event in MongoDB."""
        event_data = {
            "event_id": str(uuid.uuid4()),
            "event_type": kwargs.get("event_type", "test.event"),
            "aggregate_id": kwargs.get("aggregate_id", str(uuid.uuid4())),
            "correlation_id": kwargs.get("correlation_id", str(uuid.uuid4())),
            "payload": kwargs.get("payload", {}),
            "metadata": kwargs.get("metadata", {}),
            "timestamp": asyncio.get_event_loop().time(),
            "user_id": kwargs.get("user_id", str(uuid.uuid4()))
        }
        event_data.update(kwargs)
        
        result = await db.events.insert_one(event_data)
        event_data["_id"] = result.inserted_id
        return event_data
    
    @staticmethod
    async def publish_test_event(producer: Optional[AIOKafkaProducer], topic: str, event: Dict[str, Any]):
        """Publish test event to Kafka if available."""
        if not producer:
            return None
        
        import json
        value = json.dumps(event).encode("utf-8")
        key = event.get("aggregate_id", str(uuid.uuid4())).encode("utf-8")
        
        return await producer.send_and_wait(topic, value=value, key=key)
    
    @staticmethod
    async def cache_test_data(client: redis.Redis, key: str, data: Any, ttl: int = 60):
        """Cache test data in Redis."""
        import json
        if isinstance(data, dict):
            data = json.dumps(data)
        await client.setex(key, ttl, data)
        
    @staticmethod
    async def get_cached_data(client: redis.Redis, key: str) -> Optional[Any]:
        """Get cached test data from Redis."""
        import json
        data = await client.get(key)
        if data:
            try:
                return json.loads(data)
            except (json.JSONDecodeError, TypeError):
                return data
        return None


@pytest.fixture
def test_data_factory():
    """Provide test data factory."""
    return TestDataFactory()


async def wait_for_service(check_func, timeout: int = 30, service_name: str = "service"):
    """Wait for a service to be ready."""
    import time
    start = time.time()
    last_error = None
    
    while time.time() - start < timeout:
        try:
            await check_func()
            return True
        except Exception as e:
            last_error = e
            await asyncio.sleep(0.5)
    
    raise TimeoutError(f"{service_name} not ready after {timeout}s: {last_error}")


@pytest_asyncio.fixture(scope="session")
async def ensure_services_running():
    """Ensure required Docker services are running."""
    import subprocess

    # Check MongoDB
    async def check_mongo() -> None:
        client = AsyncMongoClient(
            "mongodb://root:rootpassword@localhost:27017",
            serverSelectionTimeoutMS=5000
        )
        try:
            await client.admin.command("ping")
        finally:
            await client.close()

    try:
        await check_mongo()
    except Exception:
        print("Starting MongoDB...")
        subprocess.run(["docker-compose", "up", "-d", "mongo"], check=False)
        await wait_for_service(check_mongo, service_name="MongoDB")

    # Check Redis
    async def check_redis() -> None:
        r = redis.Redis(host="localhost", port=6379, socket_connect_timeout=5)
        try:
            await r.execute_command("PING")
        finally:
            await r.aclose()

    try:
        await check_redis()
    except Exception:
        print("Starting Redis...")
        subprocess.run(["docker-compose", "up", "-d", "redis"], check=False)
        await wait_for_service(check_redis, service_name="Redis")
    
    # Kafka is optional - don't fail if not available
    try:
        producer = AIOKafkaProducer(bootstrap_servers="localhost:9092")
        await asyncio.wait_for(producer.start(), timeout=5)
        await producer.stop()
    except Exception:
        print("Kafka not available - some tests may be skipped")
    
    yield
    
    # Services stay running for next test run