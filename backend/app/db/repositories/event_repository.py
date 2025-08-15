import time
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Mapping

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.errors import DuplicateKeyError

from app.core.logging import logger
from app.core.metrics import MONGODB_EVENT_OPERATIONS, MONGODB_EVENT_QUERY_DURATION
from app.domain.events import (
    ArchivedEvent,
    Event,
    EventAggregationResult,
    EventFields,
    EventFilter,
    EventListResult,
    EventReplayInfo,
    EventStatistics,
)
from app.schemas_pydantic.user import UserRole


class EventRepository:
    """Repository for event store operations."""

    def __init__(self, database: AsyncIOMotorDatabase) -> None:
        self.database = database
        self._collection: AsyncIOMotorCollection | None = None
        self._initialized = False

    @property
    def collection(self) -> AsyncIOMotorCollection:
        if self._collection is None:
            self._collection = self.database.events
        return self._collection

    async def initialize(self) -> None:
        if self._initialized:
            return

        try:
            try:
                # Try to create indexes without names to avoid conflicts
                indexes = [
                    IndexModel([(str(EventFields.EVENT_ID), ASCENDING)], unique=True),
                    IndexModel([(str(EventFields.EVENT_TYPE), ASCENDING), (str(EventFields.TIMESTAMP), DESCENDING)]),
                    IndexModel([(str(EventFields.AGGREGATE_ID), ASCENDING), (str(EventFields.TIMESTAMP), DESCENDING)]),
                    IndexModel([(str(EventFields.CORRELATION_ID), ASCENDING)]),
                    IndexModel(
                        [(str(EventFields.METADATA_USER_ID), ASCENDING),
                         (str(EventFields.TIMESTAMP), DESCENDING)]),
                    IndexModel([(str(EventFields.METADATA_SERVICE_NAME), ASCENDING),
                                (str(EventFields.TIMESTAMP), DESCENDING)]),
                    IndexModel([(str(EventFields.STATUS), ASCENDING), (str(EventFields.TIMESTAMP), DESCENDING)]),
                    IndexModel([(str(EventFields.PAYLOAD_EXECUTION_ID), ASCENDING)], sparse=True),
                    IndexModel([(str(EventFields.PAYLOAD_POD_NAME), ASCENDING)], sparse=True),
                ]
                await self.collection.create_indexes(indexes)
            except Exception as e:
                # Ignore index conflicts
                if "IndexOptionsConflict" not in str(e):
                    logger.error(f"Failed to create indexes: {e}")
                else:
                    logger.info("Some indexes already exist, continuing...")
            logger.info("Event collection indexes created successfully")

            await self._set_collection_options()

            self._initialized = True

        except Exception as e:
            logger.error(f"Failed to initialize event collection: {e}")
            raise

    async def _set_collection_options(self) -> None:
        try:
            await self.database.command({
                "collMod": "events",
                "validator": {
                    "$jsonSchema": {
                        "bsonType": "object",
                        "required": ["event_id", "event_type", "timestamp", "event_version"],
                        "properties": {
                            "event_id": {
                                "bsonType": "string",
                                "description": "Unique event identifier"
                            },
                            "event_type": {
                                "bsonType": "string",
                                "description": "Type of event"
                            },
                            "timestamp": {
                                "bsonType": "date",
                                "description": "Event timestamp"
                            },
                            "event_version": {
                                "bsonType": "string",
                                "pattern": "^\\d+\\.\\d+$",
                                "description": "Event schema version"
                            },
                            "aggregate_id": {
                                "bsonType": ["string", "null"],
                                "description": "Aggregate root identifier"
                            },
                            "correlation_id": {
                                "bsonType": ["string", "null"],
                                "description": "Correlation identifier for tracing"
                            },
                            "metadata": {
                                "bsonType": "object",
                                "properties": {
                                    "user_id": {"bsonType": ["string", "null"]},
                                    "service_name": {"bsonType": "string"},
                                    "service_version": {"bsonType": "string"},
                                    "ip_address": {"bsonType": ["string", "null"]},
                                    "user_agent": {"bsonType": ["string", "null"]},
                                    "session_id": {"bsonType": ["string", "null"]}
                                }
                            },
                            "payload": {
                                "bsonType": "object",
                                "description": "Event-specific data"
                            }
                        }
                    }
                },
                "validationLevel": "moderate",
                "validationAction": "warn"
            })
            logger.info("Event collection validation rules set")
        except Exception as e:
            logger.warning(f"Could not set collection validation: {e}")

    async def store_event(self, event: Event) -> str:
        """
        Store an event in the collection
        
        Args:
            event: Event domain model to store
            
        Returns:
            Event ID of stored event
            
        Raises:
            DuplicateKeyError: If event with same ID already exists
        """
        start_time = time.time()

        try:
            # Set stored_at if not already set
            if not event.stored_at:
                event.stored_at = datetime.now(timezone.utc)

            event_doc = event.to_dict()
            _ = await self.collection.insert_one(event_doc)

            MONGODB_EVENT_OPERATIONS.labels(operation="insert", status="success").inc()
            MONGODB_EVENT_QUERY_DURATION.labels(operation="insert").observe(time.time() - start_time)

            logger.debug(f"Stored event {event.event_id} of type {event.event_type}")
            return event.event_id

        except DuplicateKeyError:
            MONGODB_EVENT_OPERATIONS.labels(operation="insert", status="duplicate").inc()
            MONGODB_EVENT_QUERY_DURATION.labels(operation="insert").observe(time.time() - start_time)
            logger.warning(f"Duplicate event ID: {event.event_id}")
            raise
        except Exception as e:
            MONGODB_EVENT_OPERATIONS.labels(operation="insert", status="error").inc()
            MONGODB_EVENT_QUERY_DURATION.labels(operation="insert").observe(time.time() - start_time)
            logger.error(f"Failed to store event: {e}")
            raise

    async def store_events_batch(self, events: list[Event]) -> list[str]:
        """
        Store multiple events in a batch
        
        Args:
            events: List of event domain models to store
            
        Returns:
            List of stored event IDs
        """
        if not events:
            return []

        try:
            # Convert events to documents and set stored_at
            event_docs = []
            for event in events:
                if not event.stored_at:
                    event.stored_at = datetime.now(timezone.utc)
                event_docs.append(event.to_dict())

            result = await self.collection.insert_many(event_docs, ordered=False)

            logger.info(f"Stored {len(result.inserted_ids)} events in batch")
            return [event.event_id for event in events]

        except Exception as e:
            logger.error(f"Failed to store event batch: {e}")
            stored_ids = []
            for event in events:
                try:
                    await self.store_event(event)
                    stored_ids.append(event.event_id)
                except DuplicateKeyError:
                    continue
            return stored_ids

    async def get_event(self, event_id: str) -> Event | None:
        start_time = time.time()

        try:
            result = await self.collection.find_one({str(EventFields.EVENT_ID): event_id})
            MONGODB_EVENT_OPERATIONS.labels(operation="find_one", status="success").inc()
            MONGODB_EVENT_QUERY_DURATION.labels(operation="find_one").observe(time.time() - start_time)
            return Event.from_dict(result) if result else None
        except Exception as e:
            MONGODB_EVENT_OPERATIONS.labels(operation="find_one", status="error").inc()
            MONGODB_EVENT_QUERY_DURATION.labels(operation="find_one").observe(time.time() - start_time)
            logger.error(f"Failed to get event: {e}")
            return None

    async def get_events_by_type(
            self,
            event_type: str,
            start_time: datetime | None = None,
            end_time: datetime | None = None,
            limit: int = 100,
            skip: int = 0
    ) -> list[Event]:
        query: dict[str, object] = {str(EventFields.EVENT_TYPE): event_type}

        if start_time or end_time:
            time_query: dict[str, object] = {}
            if start_time:
                time_query["$gte"] = start_time
            if end_time:
                time_query["$lte"] = end_time
            query[str(EventFields.TIMESTAMP)] = time_query

        cursor = self.collection.find(query).sort(str(EventFields.TIMESTAMP), DESCENDING).skip(skip).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [Event.from_dict(doc) for doc in docs]

    async def get_events_by_aggregate(
            self,
            aggregate_id: str,
            event_types: list[str] | None = None,
            limit: int = 100
    ) -> list[Event]:
        start_time = time.time()

        try:
            query: dict[str, object] = {str(EventFields.AGGREGATE_ID): aggregate_id}

            if event_types:
                query[str(EventFields.EVENT_TYPE)] = {"$in": event_types}

            cursor = self.collection.find(query).sort(str(EventFields.TIMESTAMP), ASCENDING).limit(limit)
            docs = await cursor.to_list(length=limit)

            MONGODB_EVENT_OPERATIONS.labels(operation="find_by_aggregate", status="success").inc()
            MONGODB_EVENT_QUERY_DURATION.labels(operation="find_by_aggregate").observe(time.time() - start_time)
            return [Event.from_dict(doc) for doc in docs]
        except Exception as e:
            MONGODB_EVENT_OPERATIONS.labels(operation="find_by_aggregate", status="error").inc()
            MONGODB_EVENT_QUERY_DURATION.labels(operation="find_by_aggregate").observe(time.time() - start_time)
            logger.error(f"Failed to get events by aggregate: {e}")
            return []

    async def get_events_by_correlation(
            self,
            correlation_id: str,
            limit: int = 100
    ) -> list[Event]:
        cursor = (self.collection.find({str(EventFields.CORRELATION_ID): correlation_id})
                  .sort(str(EventFields.TIMESTAMP), ASCENDING).limit(limit))
        docs = await cursor.to_list(length=limit)
        return [Event.from_dict(doc) for doc in docs]

    async def get_events_by_user(
            self,
            user_id: str,
            event_types: list[str] | None = None,
            start_time: datetime | None = None,
            end_time: datetime | None = None,
            limit: int = 100,
            skip: int = 0
    ) -> list[Event]:
        query: dict[str, object] = {str(EventFields.METADATA_USER_ID): user_id}

        if event_types:
            query[str(EventFields.EVENT_TYPE)] = {"$in": event_types}

        if start_time or end_time:
            time_query: dict[str, object] = {}
            if start_time:
                time_query["$gte"] = start_time
            if end_time:
                time_query["$lte"] = end_time
            query[str(EventFields.TIMESTAMP)] = time_query

        cursor = self.collection.find(query).sort(str(EventFields.TIMESTAMP), DESCENDING).skip(skip).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [Event.from_dict(doc) for doc in docs]

    async def get_execution_events(
            self,
            execution_id: str,
            limit: int = 100
    ) -> list[Event]:
        query = {
            "$or": [
                {EventFields.PAYLOAD_EXECUTION_ID: execution_id},
                {EventFields.AGGREGATE_ID: execution_id}
            ]
        }

        cursor = self.collection.find(query).sort(str(EventFields.TIMESTAMP), ASCENDING).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [Event.from_dict(doc) for doc in docs]

    async def search_events(
            self,
            text_query: str,
            filters: dict[str, object] | None = None,
            limit: int = 100,
            skip: int = 0
    ) -> list[Event]:
        query: dict[str, object] = {"$text": {"$search": text_query}}

        if filters:
            query.update(filters)

        cursor = self.collection.find(query).sort(str(EventFields.TIMESTAMP), DESCENDING).skip(skip).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [Event.from_dict(doc) for doc in docs]

    async def get_event_statistics(
            self,
            start_time: datetime | None = None,
            end_time: datetime | None = None
    ) -> EventStatistics:
        pipeline: list[Mapping[str, object]] = []

        if start_time or end_time:
            match_stage = {}
            if start_time:
                match_stage[EventFields.TIMESTAMP] = {"$gte": start_time}
            if end_time:
                match_stage.setdefault(EventFields.TIMESTAMP, {})["$lte"] = end_time
            pipeline.append({"$match": match_stage})

        pipeline.extend([
            {
                "$facet": {
                    "by_type": [
                        {"$group": {"_id": f"${str(EventFields.EVENT_TYPE)}", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}}
                    ],
                    "by_service": [
                        {"$group": {"_id": f"${str(EventFields.METADATA_SERVICE_NAME)}", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}}
                    ],
                    "by_hour": [
                        {
                            "$group": {
                                "_id": {
                                    "$dateToString": {
                                        "format": "%Y-%m-%d %H:00",
                                        "date": f"${str(EventFields.TIMESTAMP)}"
                                    }
                                },
                                "count": {"$sum": 1}
                            }
                        },
                        {"$sort": {"_id": 1}}
                    ],
                    "total": [
                        {"$count": "count"}
                    ]
                }
            }
        ])

        result = await self.collection.aggregate(pipeline).to_list(length=1)

        if result:
            stats = result[0]
            return EventStatistics(
                total_events=stats["total"][0]["count"] if stats["total"] else 0,
                events_by_type={item["_id"]: item["count"] for item in stats["by_type"]},
                events_by_service={item["_id"]: item["count"] for item in stats["by_service"]},
                events_by_hour=stats["by_hour"]
            )

        return EventStatistics(
            total_events=0,
            events_by_type={},
            events_by_service={},
            events_by_hour=[]
        )

    async def stream_events(
            self,
            filters: dict[str, object] | None = None,
            start_after: dict[str, object] | None = None
    ) -> AsyncIterator[dict[str, object]]:
        """
        Stream events using change streams for real-time updates
        
        Args:
            filters: Optional filters for events
            start_after: Resume token for continuing from previous position
        """
        pipeline: list[Mapping[str, object]] = []
        if filters:
            pipeline.append({"$match": filters})

        async with self.collection.watch(
                pipeline,
                start_after=start_after,
                full_document="updateLookup"
        ) as stream:
            async for change in stream:
                if change["operationType"] in ["insert", "update", "replace"]:
                    yield change["fullDocument"]

    async def cleanup_old_events(
            self,
            older_than_days: int = 30,
            event_types: list[str] | None = None,
            dry_run: bool = False
    ) -> int:
        """
        Manually cleanup old events (in addition to TTL)
        
        Args:
            older_than_days: Delete events older than this many days
            event_types: Only cleanup specific event types
            dry_run: If True, only count events without deleting
            
        Returns:
            Number of events deleted (or would be deleted if dry_run)
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=older_than_days)

        query: dict[str, object] = {str(EventFields.TIMESTAMP): {"$lt": cutoff_date}}
        if event_types:
            query[str(EventFields.EVENT_TYPE)] = {"$in": event_types}

        if dry_run:
            count = await self.collection.count_documents(query)
            logger.info(f"Would delete {count} events older than {older_than_days} days")
            return count

        result = await self.collection.delete_many(query)
        logger.info(f"Deleted {result.deleted_count} events older than {older_than_days} days")
        return result.deleted_count

    async def create_event_projection(
            self,
            name: str,
            pipeline: list[dict[str, object]],
            output_collection: str
    ) -> None:
        """
        Create a materialized view (projection) of events
        
        Args:
            name: Name of the projection
            pipeline: Aggregation pipeline for the projection
            output_collection: Name of the output collection
        """
        try:
            pipeline.append({"$out": output_collection})

            await self.collection.aggregate(pipeline).to_list(length=None)

            output_coll = self.database[output_collection]
            await output_coll.create_index([("_id", ASCENDING)])

            logger.info(f"Created event projection '{name}' in collection '{output_collection}'")

        except Exception as e:
            logger.error(f"Failed to create projection '{name}': {e}")
            raise

    async def get_execution_events_with_access_check(
            self,
            execution_id: str,
            user_id: str,
            user_role: str,
            include_system_events: bool = False
    ) -> list[Event] | None:
        """Get execution events with user access check"""
        events = await self.get_events_by_aggregate(aggregate_id=execution_id, limit=1000)

        if not events:
            return []

        # Check access - if first event belongs to different user, require admin role
        first_event_user = events[0].metadata.user_id
        if first_event_user and first_event_user != user_id and user_role != UserRole.ADMIN:
            return None  # Signal access denied

        # Filter out system events if requested
        if not include_system_events:
            events = [
                e for e in events
                if not e.metadata.service_name.startswith("system-")
            ]

        return events

    async def get_user_events_paginated(
            self,
            user_id: str,
            event_types: list[str] | None = None,
            start_time: datetime | None = None,
            end_time: datetime | None = None,
            limit: int = 100,
            skip: int = 0,
            sort_order: str = "desc"
    ) -> EventListResult:
        """Get paginated user events with count"""
        query: dict[str, object] = {str(EventFields.METADATA_USER_ID): user_id}

        if event_types:
            query[str(EventFields.EVENT_TYPE)] = {"$in": event_types}

        if start_time or end_time:
            time_filter = {}
            if start_time:
                time_filter["$gte"] = start_time
            if end_time:
                time_filter["$lte"] = end_time
            query[EventFields.TIMESTAMP] = time_filter

        total_count = await self.collection.count_documents(query)

        sort_direction = DESCENDING if sort_order == "desc" else ASCENDING
        cursor = self.collection.find(query)
        cursor = cursor.sort(EventFields.TIMESTAMP, sort_direction)
        cursor = cursor.skip(skip).limit(limit)

        docs = []
        async for doc in cursor:
            docs.append(doc)

        return EventListResult(
            events=[Event.from_dict(doc) for doc in docs],
            total=total_count,
            skip=skip,
            limit=limit,
            has_more=(skip + limit) < total_count
        )

    async def query_events_advanced(
            self,
            user_id: str,
            user_role: str,
            filters: EventFilter
    ) -> EventListResult | None:
        """Advanced event query with filters"""
        query: dict[str, object] = {}

        # User access control
        if filters.user_id:
            if filters.user_id != user_id and user_role != UserRole.ADMIN:
                return None  # Signal unauthorized
            query[EventFields.METADATA_USER_ID] = filters.user_id
        elif user_role != UserRole.ADMIN:
            query[str(EventFields.METADATA_USER_ID)] = user_id

        # Apply filters using EventFilter's to_query method
        base_query = filters.to_query()
        query.update(base_query)

        total_count = await self.collection.count_documents(query)

        sort_field = EventFields.TIMESTAMP
        sort_direction = DESCENDING

        cursor = self.collection.find(query)
        cursor = cursor.sort(sort_field, sort_direction)
        cursor = cursor.skip(0).limit(100)

        docs = []
        async for doc in cursor:
            docs.append(doc)

        return EventListResult(
            events=[Event.from_dict(doc) for doc in docs],
            total=total_count,
            skip=0,
            limit=100,
            has_more=100 < total_count
        )

    async def get_events_by_correlation_with_access(
            self,
            correlation_id: str,
            user_id: str,
            user_role: str,
            include_all_users: bool = False,
            limit: int = 100
    ) -> list[Event]:
        """Get events by correlation ID with access control"""
        events = await self.get_events_by_correlation(correlation_id=correlation_id, limit=limit)

        # Filter by user access unless admin and include_all_users is True
        if not include_all_users or user_role != UserRole.ADMIN:
            events = [
                event for event in events
                if event.metadata.user_id == user_id
            ]

        return events

    async def get_event_statistics_with_access(
            self,
            user_id: str,
            user_role: str,
            start_time: datetime | None = None,
            end_time: datetime | None = None,
            include_all_users: bool = False
    ) -> EventStatistics:
        """Get event statistics with access control"""
        query: dict[str, object] = {}
        if start_time or end_time:
            time_filter: dict[str, object] = {}
            if start_time:
                time_filter["$gte"] = start_time
            if end_time:
                time_filter["$lte"] = end_time
            query[str(EventFields.TIMESTAMP)] = time_filter

        # Filter by user unless admin and include_all_users is True
        if not include_all_users or user_role != UserRole.ADMIN:
            query[str(EventFields.METADATA_USER_ID)] = user_id

        total_events = await self.collection.count_documents(query)

        # Events by type
        events_by_type_pipeline: list[Mapping[str, object]] = [
            {"$match": query},
            {"$group": {"_id": f"${str(EventFields.EVENT_TYPE)}", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]

        events_by_type = {}
        async for doc in self.collection.aggregate(events_by_type_pipeline):
            events_by_type[doc["_id"]] = doc["count"]

        # Events by service
        events_by_service_pipeline: list[Mapping[str, object]] = [
            {"$match": query},
            {"$group": {"_id": f"${str(EventFields.METADATA_SERVICE_NAME)}", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]

        events_by_service = {}
        async for doc in self.collection.aggregate(events_by_service_pipeline):
            if doc["_id"]:
                events_by_service[doc["_id"]] = doc["count"]

        # Events by hour
        events_by_hour_pipeline: list[Mapping[str, object]] = [
            {"$match": query},
            {
                "$group": {
                    "_id": {
                        "$dateToString": {
                            "format": "%Y-%m-%d %H:00",
                            "date": "$timestamp"
                        }
                    },
                    "count": {"$sum": 1}
                }
            },
            {"$sort": {"_id": 1}}
        ]

        events_by_hour = []
        async for doc in self.collection.aggregate(events_by_hour_pipeline):
            events_by_hour.append({
                "hour": doc["_id"],
                "count": doc["count"]
            })

        return EventStatistics(
            total_events=total_events,
            events_by_type=events_by_type,
            events_by_service=events_by_service,
            events_by_hour=events_by_hour,
            time_range={
                "start": start_time if start_time else datetime.now(timezone.utc),
                "end": end_time if end_time else datetime.now(timezone.utc)
            } if start_time or end_time else None
        )

    async def get_event_with_access_check(
            self,
            event_id: str,
            user_id: str,
            user_role: str
    ) -> Event | None:
        """Get event with access check"""
        event = await self.get_event(event_id)

        if not event:
            return None

        # Check access
        event_user_id = event.metadata.user_id
        if event_user_id and event_user_id != user_id and user_role != UserRole.ADMIN:
            return None  # Signal access denied

        return event

    async def aggregate_events_with_access(
            self,
            user_id: str,
            user_role: str,
            pipeline: list[dict[str, object]],
            limit: int = 100
    ) -> EventAggregationResult:
        """Run aggregation pipeline with access control"""
        pipeline = pipeline.copy()

        first_stage = pipeline[0] if pipeline else {}
        has_match = "$match" in first_stage

        # Add user filter for non-admins
        if user_role != UserRole.ADMIN:
            user_filter = {EventFields.METADATA_USER_ID: user_id}
            if has_match:
                first_stage["$match"] = {
                    "$and": [first_stage["$match"], user_filter]
                }
            else:
                pipeline.insert(0, {"$match": user_filter})

        # Add limit
        pipeline.append({"$limit": limit})

        results = []
        async for doc in self.collection.aggregate(pipeline):
            if "_id" in doc and isinstance(doc["_id"], dict):
                doc["_id"] = str(doc["_id"])
            results.append(doc)

        return EventAggregationResult(
            results=results,
            pipeline=pipeline
        )

    async def list_event_types_for_user(
            self,
            user_id: str,
            user_role: str
    ) -> list[str]:
        """Get list of event types for user"""
        pipeline: list[Mapping[str, object]] = [
            {"$match": {str(EventFields.METADATA_USER_ID): user_id}},
            {"$group": {"_id": f"${str(EventFields.EVENT_TYPE)}"}},
            {"$sort": {"_id": 1}}
        ]

        # Admin can see all event types
        if user_role == UserRole.ADMIN:
            pipeline[0] = {"$match": {}}

        event_types = []
        async for doc in self.collection.aggregate(pipeline):
            event_types.append(doc["_id"])

        return event_types

    async def delete_event_with_archival(
            self,
            event_id: str,
            deleted_by: str,
            deletion_reason: str = "Admin deletion via API"
    ) -> ArchivedEvent | None:
        """Delete event and archive it"""
        event = await self.get_event(event_id)

        if not event:
            return None

        # Create archived event
        archived_event = ArchivedEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            event_version=event.event_version,
            timestamp=event.timestamp,
            metadata=event.metadata,
            payload=event.payload,
            aggregate_id=event.aggregate_id,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            stored_at=event.stored_at,
            ttl_expires_at=event.ttl_expires_at,
            status=event.status,
            deleted_at=datetime.now(timezone.utc),
            deleted_by=deleted_by,
            deletion_reason=deletion_reason
        )

        # Archive the event
        archive_collection = self.database["events_archive"]
        await archive_collection.insert_one(archived_event.to_dict())

        # Delete from main collection
        result = await self.collection.delete_one({str(EventFields.EVENT_ID): event_id})

        if result.deleted_count == 0:
            raise Exception("Failed to delete event")

        return archived_event

    async def get_aggregate_events_for_replay(
            self,
            aggregate_id: str,
            limit: int = 10000
    ) -> list[Event]:
        """Get all events for an aggregate for replay purposes"""
        events = await self.get_events_by_aggregate(
            aggregate_id=aggregate_id,
            limit=limit
        )

        if not events:
            return []

        return events

    async def get_aggregate_replay_info(
            self,
            aggregate_id: str
    ) -> EventReplayInfo | None:
        """Get aggregate events and prepare replay information"""
        events = await self.get_aggregate_events_for_replay(aggregate_id)

        if not events:
            return None

        return EventReplayInfo(
            events=events,
            event_count=len(events),
            event_types=list(set(e.event_type for e in events)),
            time_range={
                "start": min(e.timestamp for e in events),
                "end": max(e.timestamp for e in events)
            }
        )
