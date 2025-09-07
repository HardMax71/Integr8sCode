import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Mapping

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from app.core.logging import logger
from app.domain.enums.user import UserRole
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
from app.infrastructure.mappers.event_mapper import ArchivedEventMapper, EventMapper


class EventRepository:
    def __init__(self, database: AsyncIOMotorDatabase) -> None:
        self.database = database
        self._collection: AsyncIOMotorCollection | None = None
        self.mapper = EventMapper()

    @property
    def collection(self) -> AsyncIOMotorCollection:
        if self._collection is None:
            self._collection = self.database.events
        return self._collection


    def _build_time_filter(
            self,
            start_time: datetime | float | None,
            end_time: datetime | float | None
    ) -> dict[str, object]:
        """Build time range filter, eliminating if-else branching."""
        return {
            key: value for key, value in {
                "$gte": start_time,
                "$lte": end_time
            }.items() if value is not None
        }

    def _build_query(self, **filters: object) -> dict[str, object]:
        """Build MongoDB query from non-None filters, eliminating if-else branching."""
        query: dict[str, object] = {}

        # Handle special cases
        for key, value in filters.items():
            if value is None:
                continue

            if key == "time_range" and isinstance(value, tuple):
                start_time, end_time = value
                time_filter = self._build_time_filter(start_time, end_time)
                if time_filter:
                    query[EventFields.TIMESTAMP] = time_filter
            elif key == "event_types" and isinstance(value, list):
                query[EventFields.EVENT_TYPE] = {"$in": value}
            else:
                # Direct field mapping
                query[key] = value

        return query

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
        try:
            if not event.stored_at:
                event = replace(event, stored_at=datetime.now(timezone.utc))

            event_doc = self.mapper.to_mongo_document(event)
            _ = await self.collection.insert_one(event_doc)

            logger.debug(f"Stored event {event.event_id} of type {event.event_type}")
            return event.event_id

        except DuplicateKeyError:
            logger.warning(f"Duplicate event ID: {event.event_id}")
            raise
        except Exception as e:
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
            now = datetime.now(timezone.utc)
            event_docs = []
            for event in events:
                if not event.stored_at:
                    event = replace(event, stored_at=now)
                event_docs.append(self.mapper.to_mongo_document(event))

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
        try:
            result = await self.collection.find_one({EventFields.EVENT_ID: event_id})
            return self.mapper.from_mongo_document(result) if result else None
        except Exception as e:
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
        query: dict[str, Any] = {EventFields.EVENT_TYPE: event_type}
        time_filter = self._build_time_filter(start_time, end_time)
        if time_filter:
            query[EventFields.TIMESTAMP] = time_filter

        cursor = self.collection.find(query).sort(EventFields.TIMESTAMP, DESCENDING).skip(skip).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [self.mapper.from_mongo_document(doc) for doc in docs]

    async def get_events_by_aggregate(
            self,
            aggregate_id: str,
            event_types: list[str] | None = None,
            limit: int = 100
    ) -> list[Event]:
        try:
            query: dict[str, Any] = {EventFields.AGGREGATE_ID: aggregate_id}
            if event_types:
                query[EventFields.EVENT_TYPE] = {"$in": event_types}

            cursor = self.collection.find(query).sort(EventFields.TIMESTAMP, ASCENDING).limit(limit)
            docs = await cursor.to_list(length=limit)
            return [self.mapper.from_mongo_document(doc) for doc in docs]
        except Exception as e:
            logger.error(f"Failed to get events by aggregate: {e}")
            return []

    async def get_events_by_correlation(
            self,
            correlation_id: str,
            limit: int = 100
    ) -> list[Event]:
        cursor = (self.collection.find({EventFields.METADATA_CORRELATION_ID: correlation_id})
                  .sort(EventFields.TIMESTAMP, ASCENDING).limit(limit))
        docs = await cursor.to_list(length=limit)
        return [self.mapper.from_mongo_document(doc) for doc in docs]

    async def get_events_by_user(
            self,
            user_id: str,
            event_types: list[str] | None = None,
            start_time: datetime | None = None,
            end_time: datetime | None = None,
            limit: int = 100,
            skip: int = 0
    ) -> list[Event]:
        query: dict[str, Any] = {EventFields.METADATA_USER_ID: user_id}
        if event_types:
            query[EventFields.EVENT_TYPE] = {"$in": event_types}
        time_filter = self._build_time_filter(start_time, end_time)
        if time_filter:
            query[EventFields.TIMESTAMP] = time_filter

        cursor = self.collection.find(query).sort(EventFields.TIMESTAMP, DESCENDING).skip(skip).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [self.mapper.from_mongo_document(doc) for doc in docs]

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

        cursor = self.collection.find(query).sort(EventFields.TIMESTAMP, ASCENDING).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [self.mapper.from_mongo_document(doc) for doc in docs]

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

        cursor = self.collection.find(query).sort(EventFields.TIMESTAMP, DESCENDING).skip(skip).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [self.mapper.from_mongo_document(doc) for doc in docs]

    async def get_event_statistics(
            self,
            start_time: float | None = None,
            end_time: float | None = None
    ) -> EventStatistics:
        pipeline: list[Mapping[str, object]] = []

        time_filter = self._build_time_filter(start_time, end_time)
        if time_filter:
            pipeline.append({"$match": {EventFields.TIMESTAMP: time_filter}})

        pipeline.extend([
            {
                "$facet": {
                    "by_type": [
                        {"$group": {"_id": f"${EventFields.EVENT_TYPE}", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}}
                    ],
                    "by_service": [
                        {"$group": {"_id": f"${EventFields.METADATA_SERVICE_NAME}", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}}
                    ],
                    "by_hour": [
                        {
                            "$group": {
                                "_id": {
                                    "$dateToString": {
                                        "format": "%Y-%m-%d %H:00",
                                        "date": f"${EventFields.TIMESTAMP}"
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

    async def get_event_statistics_filtered(
            self,
            match: dict[str, object] | None = None,
            start_time: datetime | None = None,
            end_time: datetime | None = None,
    ) -> EventStatistics:
        pipeline: list[Mapping[str, object]] = []

        and_clauses: list[dict[str, object]] = []
        if match:
            and_clauses.append(match)
        time_filter = self._build_time_filter(start_time, end_time)
        if time_filter:
            and_clauses.append({EventFields.TIMESTAMP: time_filter})
        if and_clauses:
            pipeline.append({"$match": {"$and": and_clauses}})

        pipeline.extend([
            {
                "$facet": {
                    "by_type": [
                        {"$group": {"_id": f"${EventFields.EVENT_TYPE}", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}}
                    ],
                    "by_service": [
                        {"$group": {"_id": f"${EventFields.METADATA_SERVICE_NAME}", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}}
                    ],
                    "by_hour": [
                        {
                            "$group": {
                                "_id": {
                                    "$dateToString": {
                                        "format": "%Y-%m-%d %H:00",
                                        "date": f"${EventFields.TIMESTAMP}"
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
        return EventStatistics(total_events=0, events_by_type={}, events_by_service={}, events_by_hour=[])

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
        cutoff_timestamp = time.time() - (older_than_days * 24 * 60 * 60)

        query: dict[str, Any] = {EventFields.TIMESTAMP: {"$lt": cutoff_timestamp}}
        if event_types:
            query[EventFields.EVENT_TYPE] = {"$in": event_types}

        if dry_run:
            count = await self.collection.count_documents(query)
            logger.info(f"Would delete {count} events older than {older_than_days} days")
            return count

        result = await self.collection.delete_many(query)
        logger.info(f"Deleted {result.deleted_count} events older than {older_than_days} days")
        return result.deleted_count

    # Access checks are handled in the service layer.

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
        query: dict[str, Any] = {EventFields.METADATA_USER_ID: user_id}
        if event_types:
            query[EventFields.EVENT_TYPE] = {"$in": event_types}
        time_filter = self._build_time_filter(start_time, end_time)
        if time_filter:
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
            events=[self.mapper.from_mongo_document(doc) for doc in docs],
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
            query[EventFields.METADATA_USER_ID] = user_id

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
            events=[self.mapper.from_mongo_document(doc) for doc in docs],
            total=total_count,
            skip=0,
            limit=100,
            has_more=100 < total_count
        )

    # Access checks are handled in the service layer.

    # Access checks are handled in the service layer.

    # Access checks are handled in the service layer.

    # Access checks are handled in the service layer.

    async def aggregate_events(
            self,
            pipeline: list[dict[str, object]],
            limit: int = 100
    ) -> EventAggregationResult:
        pipeline = pipeline.copy()
        pipeline.append({"$limit": limit})

        results = []
        async for doc in self.collection.aggregate(pipeline):
            if "_id" in doc and isinstance(doc["_id"], dict):
                doc["_id"] = str(doc["_id"])
            results.append(doc)

        return EventAggregationResult(results=results, pipeline=pipeline)

    # Access checks are handled in the service layer.

    async def list_event_types(self, match: dict[str, object] | None = None) -> list[str]:
        pipeline: list[Mapping[str, object]] = []
        if match:
            pipeline.append({"$match": match})
        pipeline.extend([
            {"$group": {"_id": f"${EventFields.EVENT_TYPE}"}},
            {"$sort": {"_id": 1}}
        ])
        event_types: list[str] = []
        async for doc in self.collection.aggregate(pipeline):
            event_types.append(doc["_id"])
        return event_types

    async def query_events_generic(
            self,
            query: dict[str, object],
            sort_field: str,
            sort_direction: int,
            skip: int,
            limit: int,
    ) -> EventListResult:
        total_count = await self.collection.count_documents(query)

        cursor = self.collection.find(query)
        cursor = cursor.sort(sort_field, sort_direction)
        cursor = cursor.skip(skip).limit(limit)

        docs = []
        async for doc in cursor:
            docs.append(doc)

        return EventListResult(
            events=[self.mapper.from_mongo_document(doc) for doc in docs],
            total=total_count,
            skip=skip,
            limit=limit,
            has_more=(skip + limit) < total_count,
        )

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
            stored_at=event.stored_at,
            ttl_expires_at=event.ttl_expires_at,
            status=event.status,
            error=event.error,
            deleted_at=datetime.now(timezone.utc),
            deleted_by=deleted_by,
            deletion_reason=deletion_reason
        )

        # Archive the event
        archive_collection = self.database["events_archive"]
        archived_mapper = ArchivedEventMapper()
        await archive_collection.insert_one(archived_mapper.to_mongo_document(archived_event))

        # Delete from main collection
        result = await self.collection.delete_one({EventFields.EVENT_ID: event_id})

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
            start_time=min(e.timestamp for e in events),
            end_time=max(e.timestamp for e in events)
        )
