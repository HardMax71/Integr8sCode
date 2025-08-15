import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.errors import BulkWriteError, DuplicateKeyError

from app.core.logging import logger
from app.events.core.consumer import ConsumerConfig, UnifiedConsumer
from app.events.core.consumer_group_names import GroupId
from app.events.core.metrics import (
    EVENTS_STORE_FAILED,
    EVENTS_STORED,
    QUERY_DURATION,
    STORE_DURATION,
)
from app.events.schema.schema_registry import SchemaRegistryManager
from app.schemas_avro.event_schemas import BaseEvent, EventType, KafkaTopic, deserialize_event


class EventStore:
    """Stores events in MongoDB with proper indexing and querying capabilities"""

    def __init__(
            self,
            db: AsyncIOMotorDatabase,
            collection_name: str = "events",
            ttl_days: int = 90,
            batch_size: int = 100,
    ):
        self.db = db
        self.collection_name = collection_name
        self.collection: AsyncIOMotorCollection = db[collection_name]
        self.ttl_days = ttl_days
        self.batch_size = batch_size
        self._initialized = False

        # Projection collections for different query patterns
        self.execution_events: AsyncIOMotorCollection = db["execution_events"]
        self.user_events: AsyncIOMotorCollection = db["user_events"]
        self.security_events: AsyncIOMotorCollection = db["security_events"]

    async def initialize(self) -> None:
        """Initialize collections with indexes"""
        if self._initialized:
            return

        try:
            # Main events collection indexes
            event_indexes = [
                IndexModel("event_id", unique=True),
                IndexModel("event_type"),
                IndexModel([("timestamp", DESCENDING)]),
                IndexModel("metadata.correlation_id"),
                IndexModel("metadata.user_id"),
                IndexModel("metadata.service_name"),
                IndexModel([("event_type", ASCENDING), ("timestamp", DESCENDING)]),
                IndexModel(
                    "timestamp",
                    expireAfterSeconds=self.ttl_days * 24 * 60 * 60,
                    name="timestamp_ttl"
                ),
            ]

            try:
                await self.collection.create_indexes(event_indexes)
            except Exception as e:
                if "IndexOptionsConflict" in str(e):
                    logger.warning(f"Index conflict in {self.collection_name}, indexes may already exist")
                else:
                    raise

            # Execution events projection indexes
            execution_indexes = [
                IndexModel("execution_id"),
                IndexModel("event_type"),
                IndexModel([("timestamp", DESCENDING)]),
                IndexModel([("execution_id", ASCENDING), ("timestamp", ASCENDING)]),
                IndexModel([("user_id", ASCENDING), ("timestamp", DESCENDING)]),
                IndexModel(
                    "timestamp",
                    expireAfterSeconds=self.ttl_days * 24 * 60 * 60,
                    name="timestamp_ttl"
                ),
            ]

            try:
                await self.execution_events.create_indexes(execution_indexes)
            except Exception as e:
                if "IndexOptionsConflict" in str(e):
                    logger.warning("Index conflict in execution_events, indexes may already exist")
                else:
                    raise

            # User events projection indexes
            user_indexes = [
                IndexModel("user_id"),
                IndexModel("event_type"),
                IndexModel([("timestamp", DESCENDING)]),
                IndexModel([("user_id", ASCENDING), ("timestamp", DESCENDING)]),
                IndexModel([("user_id", ASCENDING), ("event_type", ASCENDING)]),
                IndexModel(
                    "timestamp",
                    expireAfterSeconds=self.ttl_days * 24 * 60 * 60,
                    name="timestamp_ttl"
                ),
            ]

            try:
                await self.user_events.create_indexes(user_indexes)
            except Exception as e:
                if "IndexOptionsConflict" in str(e):
                    logger.warning("Index conflict in user_events, indexes may already exist")
                else:
                    raise

            # Security events projection indexes
            security_indexes = [
                IndexModel("event_type"),
                IndexModel([("timestamp", DESCENDING)]),
                IndexModel("user_id"),
                IndexModel("metadata.ip_address"),
                IndexModel([("event_type", ASCENDING), ("timestamp", DESCENDING)]),
                IndexModel([("user_id", ASCENDING), ("timestamp", DESCENDING)]),
                IndexModel(
                    "timestamp",
                    expireAfterSeconds=30 * 24 * 60 * 60,  # 30 days for security events
                    name="timestamp_ttl"
                ),
            ]

            try:
                await self.security_events.create_indexes(security_indexes)
            except Exception as e:
                if "IndexOptionsConflict" in str(e):
                    logger.warning("Index conflict in security_events, indexes may already exist")
                else:
                    raise

            self._initialized = True
            logger.info("Event store initialized with indexes")

        except Exception as e:
            logger.error(f"Failed to initialize event store: {e}")
            raise

    async def store_event(self, event: BaseEvent) -> bool:
        """Store a single event"""
        start_time = asyncio.get_event_loop().time()

        try:
            event_dict = event.model_dump()
            event_dict["stored_at"] = datetime.now(timezone.utc)

            # Store in main collection
            await self.collection.insert_one(event_dict)

            # Store in projections based on event type
            await self._update_projections(event, event_dict)

            # Update metrics
            duration = asyncio.get_event_loop().time() - start_time
            STORE_DURATION.labels(
                operation="store_single",
                collection=self.collection_name
            ).observe(duration)

            EVENTS_STORED.labels(
                event_type=event.event_type,
                collection=self.collection_name
            ).inc()

            return True

        except DuplicateKeyError:
            logger.warning(f"Event {event.event_id} already exists")
            return True  # Idempotent behavior

        except Exception as e:
            logger.error(f"Failed to store event {event.event_id}: {e.__class__.__name__}: {str(e)}", exc_info=True)
            EVENTS_STORE_FAILED.labels(
                event_type=event.event_type,
                error_type=type(e).__name__
            ).inc()
            return False

    async def store_batch(self, events: List[BaseEvent]) -> Dict[str, int]:
        """Store multiple events in batch"""
        start_time = asyncio.get_event_loop().time()
        results = {"total": len(events), "stored": 0, "duplicates": 0, "failed": 0}

        if not events:
            return results

        try:
            # Prepare documents
            documents = []
            projection_updates: Dict[str, List[Dict[str, Any]]] = {
                "execution": [],
                "user": [],
                "security": []
            }

            for event in events:
                # Use model_dump to get dict representation
                event_dict = event.model_dump()
                event_dict["stored_at"] = datetime.now(timezone.utc)
                documents.append(event_dict)

                # Prepare projection updates
                self._prepare_projection_update(event, event_dict, projection_updates)

            # Bulk insert with ordered=False to continue on duplicates
            try:
                result = await self.collection.insert_many(documents, ordered=False)
                results["stored"] = len(result.inserted_ids)
            except Exception as e:
                # Handle partial success
                if isinstance(e, BulkWriteError) and e.details:
                    write_errors = e.details.get("writeErrors", [])
                    for error in write_errors:
                        if error.get("code") == 11000:  # Duplicate key
                            results["duplicates"] += 1
                        else:
                            results["failed"] += 1
                    results["stored"] = results["total"] - results["duplicates"] - results["failed"]
                else:
                    raise

            # Update projections
            await self._bulk_update_projections(projection_updates)

            # Update metrics
            duration = asyncio.get_event_loop().time() - start_time
            STORE_DURATION.labels(
                operation="store_batch",
                collection=self.collection_name
            ).observe(duration)

            for event in events:
                if results["stored"] > 0:
                    EVENTS_STORED.labels(
                        event_type=event.event_type,
                        collection=self.collection_name
                    ).inc()

            return results

        except Exception as e:
            logger.error(f"Failed to store batch: {e.__class__.__name__}: {str(e)}", exc_info=True)
            results["failed"] = results["total"] - results["stored"]
            return results

    async def get_event(self, event_id: str) -> Optional[BaseEvent]:
        """Get event by ID"""
        start_time = asyncio.get_event_loop().time()

        try:
            # Query by event_id - MongoDB stores UUIDs as binary
            document = await self.collection.find_one({"event_id": event_id})

            if document:
                document.pop("stored_at", None)
                event = deserialize_event(document)

                # Update metrics
                duration = asyncio.get_event_loop().time() - start_time
                QUERY_DURATION.labels(
                    operation="get_by_id",
                    collection=self.collection_name
                ).observe(duration)

                return event

            return None

        except Exception as e:
            logger.error(f"Failed to get event {event_id}: {e}")
            return None

    async def get_events_by_type(
            self,
            event_type: EventType,
            start_time: Optional[datetime] = None,
            end_time: Optional[datetime] = None,
            limit: int = 100,
            offset: int = 0
    ) -> List[BaseEvent]:
        """Get events by type with time range filtering"""
        query_start = asyncio.get_event_loop().time()

        try:
            query: Dict[str, Any] = {"event_type": str(event_type)}

            if start_time or end_time:
                time_query = {}
                if start_time:
                    time_query["$gte"] = start_time
                if end_time:
                    time_query["$lte"] = end_time
                query["timestamp"] = time_query

            cursor = self.collection.find(query).sort(
                "timestamp", DESCENDING
            ).skip(offset).limit(limit)

            events = []
            async for document in cursor:
                document.pop("stored_at", None)
                event = deserialize_event(document)
                if event:
                    events.append(event)

            # Update metrics
            duration = asyncio.get_event_loop().time() - query_start
            QUERY_DURATION.labels(
                operation="get_by_type",
                collection=self.collection_name
            ).observe(duration)

            return events

        except Exception as e:
            logger.error(f"Failed to get events by type: {e}")
            return []

    async def get_execution_events(
            self,
            execution_id: str,
            event_types: Optional[List[EventType]] = None
    ) -> List[BaseEvent]:
        """Get all events for an execution"""
        query_start = asyncio.get_event_loop().time()

        try:
            # MongoDB stores UUIDs as binary, so use the UUID object directly
            query: Dict[str, Any] = {"execution_id": execution_id}
            if event_types:
                query["event_type"] = {"$in": [str(et) for et in event_types]}

            cursor = self.execution_events.find(query).sort("timestamp", ASCENDING)

            events = []
            async for document in cursor:
                event = deserialize_event(document)
                if event:
                    events.append(event)

            # Update metrics
            duration = asyncio.get_event_loop().time() - query_start
            QUERY_DURATION.labels(
                operation="get_execution_events",
                collection="execution_events"
            ).observe(duration)

            return events

        except Exception as e:
            logger.error(f"Failed to get execution events: {e}")
            return []

    async def get_user_events(
            self,
            user_id: str,
            event_types: Optional[List[EventType]] = None,
            start_time: Optional[datetime] = None,
            end_time: Optional[datetime] = None,
            limit: int = 100
    ) -> List[BaseEvent]:
        """Get events for a user"""
        query_start = asyncio.get_event_loop().time()

        try:
            query: Dict[str, Any] = {"user_id": str(user_id)}

            if event_types:
                query["event_type"] = {"$in": [str(et) for et in event_types]}

            if start_time or end_time:
                time_query = {}
                if start_time:
                    time_query["$gte"] = start_time
                if end_time:
                    time_query["$lte"] = end_time
                query["timestamp"] = time_query

            cursor = self.user_events.find(query).sort(
                "timestamp", DESCENDING
            ).limit(limit)

            events = []
            async for document in cursor:
                event = deserialize_event(document)
                if event:
                    events.append(event)

            # Update metrics
            duration = asyncio.get_event_loop().time() - query_start
            QUERY_DURATION.labels(
                operation="get_user_events",
                collection="user_events"
            ).observe(duration)

            return events

        except Exception as e:
            logger.error(f"Failed to get user events: {e}")
            return []

    async def get_correlation_chain(self, correlation_id: str) -> List[BaseEvent]:
        """Get all events in a correlation chain"""
        query_start = asyncio.get_event_loop().time()

        try:
            # Correlation ID is stored as string in metadata
            query = {"metadata.correlation_id": str(correlation_id)}
            cursor = self.collection.find(query).sort("timestamp", ASCENDING)

            events = []
            async for document in cursor:
                document.pop("stored_at", None)
                event = deserialize_event(document)
                if event:
                    events.append(event)

            # Update metrics
            duration = asyncio.get_event_loop().time() - query_start
            QUERY_DURATION.labels(
                operation="get_correlation_chain",
                collection=self.collection_name
            ).observe(duration)

            return events

        except Exception as e:
            logger.error(f"Failed to get correlation chain: {e}")
            return []

    async def replay_events(
            self,
            start_time: datetime,
            end_time: Optional[datetime] = None,
            event_types: Optional[List[EventType]] = None,
            callback: Optional[Callable[[BaseEvent], Any]] = None
    ) -> int:
        """Replay events in chronological order"""
        query_start = asyncio.get_event_loop().time()
        count = 0

        try:
            query: Dict[str, Any] = {"timestamp": {"$gte": start_time}}
            if end_time:
                query["timestamp"]["$lte"] = end_time
            if event_types:
                query["event_type"] = {"$in": [str(et) for et in event_types]}

            cursor = self.collection.find(query).sort("timestamp", ASCENDING)

            async for document in cursor:
                document.pop("stored_at", None)
                event = deserialize_event(document)

                if event and callback:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(event)
                    else:
                        await asyncio.to_thread(callback, event)

                count += 1

            # Update metrics
            duration = asyncio.get_event_loop().time() - query_start
            QUERY_DURATION.labels(
                operation="replay_events",
                collection=self.collection_name
            ).observe(duration)

            logger.info(f"Replayed {count} events from {start_time} to {end_time}")
            return count

        except Exception as e:
            logger.error(f"Failed to replay events: {e}")
            return count

    async def _update_projections(self, event: BaseEvent, event_dict: Dict[str, Any]) -> None:
        """Update projection collections based on event type"""
        projection_updates: Dict[str, List[Dict[str, Any]]] = {
            "execution": [],
            "user": [],
            "security": []
        }

        self._prepare_projection_update(event, event_dict, projection_updates)
        await self._bulk_update_projections(projection_updates)

    def _prepare_projection_update(
            self,
            event: BaseEvent,
            event_dict: Dict[str, Any],
            updates: Dict[str, List[Dict[str, Any]]]
    ) -> None:
        """Prepare projection updates based on event type and fields"""
        # Check for execution_id in the dumped event dict
        if "execution_id" in event_dict:
            projection_doc = {
                **event_dict,
                "execution_id": event_dict["execution_id"],
                "user_id": event.metadata.user_id
            }
            updates["execution"].append(projection_doc)

        # User events projection - all events with user_id
        if event.metadata.user_id:
            projection_doc = {
                **event_dict,
                "user_id": event.metadata.user_id
            }
            updates["user"].append(projection_doc)

        # Security events projection
        security_event_types = [
            EventType.USER_LOGIN,
            EventType.USER_LOGGED_OUT,
            EventType.SECURITY_VIOLATION
        ]

        if event.event_type in security_event_types:
            projection_doc = {
                **event_dict,
                "user_id": event.metadata.user_id,
                "ip_address": event.metadata.ip_address
            }
            updates["security"].append(projection_doc)

    async def _bulk_update_projections(self, updates: Dict[str, List]) -> None:
        """Bulk update projection collections"""
        tasks = []

        if updates["execution"]:
            tasks.append(
                self.execution_events.insert_many(
                    updates["execution"],
                    ordered=False
                )
            )

        if updates["user"]:
            tasks.append(
                self.user_events.insert_many(
                    updates["user"],
                    ordered=False
                )
            )

        if updates["security"]:
            tasks.append(
                self.security_events.insert_many(
                    updates["security"],
                    ordered=False
                )
            )

        if tasks:
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as e:
                # Log but don't fail - projections are secondary
                logger.warning(f"Failed to update some projections: {e}")

    async def get_event_stats(
            self,
            start_time: Optional[datetime] = None,
            end_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Get event statistics"""
        pipeline: List[Dict[str, Any]] = []

        # Time filtering
        if start_time or end_time:
            match_stage = {}
            if start_time:
                match_stage["timestamp"] = {"$gte": start_time}
            if end_time:
                match_stage.setdefault("timestamp", {})["$lte"] = end_time
            pipeline.append({"$match": match_stage})

        # Group by event type
        pipeline.extend([
            {
                "$group": {
                    "_id": "$event_type",
                    "count": {"$sum": 1},
                    "first_event": {"$min": "$timestamp"},
                    "last_event": {"$max": "$timestamp"}
                }
            },
            {
                "$sort": {"count": -1}
            }
        ])

        cursor = self.collection.aggregate(pipeline)

        stats: Dict[str, Any] = {
            "total_events": 0,
            "event_types": {},
            "time_range": {
                "start": start_time,
                "end": end_time
            }
        }

        async for result in cursor:
            event_type = result["_id"]
            count = result["count"]
            stats["event_types"][event_type] = {
                "count": count,
                "first_event": result["first_event"],
                "last_event": result["last_event"]
            }
            stats["total_events"] += count

        return stats

    async def health_check(self) -> Dict[str, Any]:
        """Check health of event store"""
        try:
            # Try to ping the database
            await self.db.command("ping")

            # Get some basic stats
            event_count = await self.collection.count_documents({})

            return {
                "healthy": True,
                "event_count": event_count,
                "collection": self.collection_name,
                "initialized": self._initialized
            }
        except Exception as e:
            logger.error(f"Event store health check failed: {e}")
            return {
                "healthy": False,
                "error": str(e)
            }


class EventStoreConsumer:
    """Consumes events from Kafka and stores them in MongoDB"""

    def __init__(
            self,
            event_store: EventStore,
            topics: List[KafkaTopic],
            group_id: str = GroupId.EVENT_STORE_CONSUMER,
            batch_size: int = 100,
            batch_timeout_seconds: float = 5.0,
            schema_registry_manager: Optional[SchemaRegistryManager] = None
    ):
        self.event_store = event_store
        self.topics = topics
        self.group_id = group_id
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout_seconds
        self.consumer: Optional[UnifiedConsumer] = None
        self.schema_registry_manager = schema_registry_manager
        self._batch_buffer: List[BaseEvent] = []
        self._batch_lock = asyncio.Lock()
        self._last_batch_time = asyncio.get_event_loop().time()
        self._batch_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start consuming and storing events"""
        if self._running:
            return

        # Initialize event store
        await self.event_store.initialize()

        # Create consumer config
        config = ConsumerConfig(
            group_id=self.group_id,
            topics=[topic.value for topic in self.topics],  # Convert KafkaTopic to strings
            enable_auto_commit=False,
            max_poll_records=self.batch_size
        )

        self.consumer = UnifiedConsumer(config, self.schema_registry_manager)

        # Register handlers
        self.consumer.register_handler("*", self._handle_event)
        self.consumer.register_error_handler(self._handle_error)

        await self.consumer.start()
        self._running = True

        # Start batch processing task
        self._batch_task = asyncio.create_task(self._batch_processor())

        logger.info(f"Event store consumer started for topics: {self.topics}")

    async def stop(self) -> None:
        """Stop consumer"""
        if not self._running:
            return

        self._running = False

        # Process remaining batch
        await self._flush_batch()

        # Cancel batch task
        if self._batch_task:
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass

        # Stop consumer
        if self.consumer:
            await self.consumer.stop()

        logger.info("Event store consumer stopped")

    async def _handle_event(self, event: BaseEvent | dict[str, Any], record: Any) -> Any:
        """Handle incoming event"""
        if isinstance(event, dict):
            logger.warning("Received dict event in EventStore handler")
            return None
        logger.info(f"Event store received event: {event.event_type} - {event.event_id}")
        async with self._batch_lock:
            self._batch_buffer.append(event)

            # Check if batch is full
            if len(self._batch_buffer) >= self.batch_size:
                await self._flush_batch()
            return None

    async def _handle_error(self, error: Exception, record: Any = None, event: Any = None) -> None:
        """Handle processing errors"""
        logger.error(f"Error processing event: {error}", exc_info=True)

    async def _batch_processor(self) -> None:
        """Periodically flush batches based on timeout"""
        while self._running:
            try:
                await asyncio.sleep(1)  # Check every second

                async with self._batch_lock:
                    time_since_last_batch = asyncio.get_event_loop().time() - self._last_batch_time

                    if (self._batch_buffer and
                            time_since_last_batch >= self.batch_timeout):
                        await self._flush_batch()

            except Exception as e:
                logger.error(f"Error in batch processor: {e}")

    async def _flush_batch(self) -> None:
        """Flush current batch to storage"""
        if not self._batch_buffer:
            return

        batch = self._batch_buffer.copy()
        self._batch_buffer.clear()
        self._last_batch_time = asyncio.get_event_loop().time()

        logger.info(f"Event store flushing batch of {len(batch)} events")

        # Store batch
        results = await self.event_store.store_batch(batch)

        logger.info(
            f"Stored event batch: total={results['total']}, "
            f"stored={results['stored']}, duplicates={results['duplicates']}, "
            f"failed={results['failed']}"
        )

        # Commit offsets only for successfully stored events
        if results["stored"] > 0 or results["duplicates"] > 0:
            if self.consumer:
                await self.consumer._commit_offsets()


def create_event_store(
        db: AsyncIOMotorDatabase,
        collection_name: str = "events",
        ttl_days: int = 90,
        batch_size: int = 100
) -> EventStore:
    """Factory function to create an EventStore instance.
    
    Args:
        db: MongoDB database instance
        collection_name: Name of the collection to store events
        ttl_days: Time-to-live for events in days
        batch_size: Batch size for bulk operations
        
    Returns:
        A new EventStore instance
    """
    return EventStore(
        db=db,
        collection_name=collection_name,
        ttl_days=ttl_days,
        batch_size=batch_size
    )


def create_event_store_consumer(
        event_store: EventStore,
        topics: List[KafkaTopic],
        group_id: str = GroupId.EVENT_STORE_CONSUMER,
        batch_size: int = 100,
        batch_timeout_seconds: float = 5.0,
        schema_registry_manager: Optional[SchemaRegistryManager] = None
) -> EventStoreConsumer:
    """Factory function to create an EventStoreConsumer instance.
    
    Args:
        event_store: EventStore instance for storing events
        topics: List of Kafka topics to consume from
        group_id: Kafka consumer group ID
        batch_size: Batch size for processing
        batch_timeout_seconds: Timeout for batch processing
        schema_registry_manager: Optional schema registry manager
        
    Returns:
        A new EventStoreConsumer instance
    """
    return EventStoreConsumer(
        event_store=event_store,
        topics=topics,
        group_id=group_id,
        batch_size=batch_size,
        batch_timeout_seconds=batch_timeout_seconds,
        schema_registry_manager=schema_registry_manager
    )
