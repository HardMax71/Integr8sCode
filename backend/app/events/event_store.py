import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Dict, List

from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.errors import BulkWriteError, DuplicateKeyError

from app.core.database_context import Collection, Cursor, Database
from app.core.logging import logger
from app.core.metrics.context import get_event_metrics
from app.core.tracing import EventAttributes
from app.core.tracing.utils import add_span_attributes
from app.domain.enums.events import EventType
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.base import BaseEvent


class EventStore:
    def __init__(
        self,
        db: Database,
        schema_registry: SchemaRegistryManager,
        collection_name: str = "events",
        ttl_days: int = 90,
        batch_size: int = 100,
    ):
        self.db = db
        self.metrics = get_event_metrics()
        self.schema_registry = schema_registry
        self.collection_name = collection_name
        self.collection: Collection = db[collection_name]
        self.ttl_days = ttl_days
        self.batch_size = batch_size
        self._initialized = False

        self._PROJECTION = {"stored_at": 0, "_id": 0}
        self._SECURITY_TYPES = [  # stringified once
            EventType.USER_LOGIN,
            EventType.USER_LOGGED_OUT,
            EventType.SECURITY_VIOLATION,
        ]

    async def initialize(self) -> None:
        if self._initialized:
            return

        event_indexes = [
            IndexModel("event_id", unique=True),
            IndexModel([("timestamp", DESCENDING)]),
            IndexModel([("event_type", ASCENDING), ("timestamp", DESCENDING)]),
            IndexModel([("metadata.user_id", ASCENDING), ("timestamp", DESCENDING)]),
            IndexModel([("metadata.user_id", ASCENDING), ("event_type", ASCENDING)]),
            IndexModel([("execution_id", ASCENDING), ("timestamp", ASCENDING)]),
            IndexModel("metadata.correlation_id"),
            IndexModel("metadata.service_name"),
            IndexModel(
                [
                    ("event_type", ASCENDING),
                    ("metadata.user_id", ASCENDING),
                    ("timestamp", DESCENDING),
                ]
            ),
            IndexModel(
                "timestamp",
                expireAfterSeconds=self.ttl_days * 24 * 60 * 60,
                name="timestamp_ttl",
            ),
        ]

        indexes_cursor = await self.collection.list_indexes()
        existing = await indexes_cursor.to_list(None)
        if len(existing) <= 1:
            await self.collection.create_indexes(event_indexes)
        logger.info(f"Created {len(event_indexes)} indexes for events collection")

        self._initialized = True
        logger.info("Streamlined event store initialized")

    async def store_event(self, event: BaseEvent) -> bool:
        start = asyncio.get_event_loop().time()
        try:
            doc = event.model_dump()
            doc["stored_at"] = datetime.now(timezone.utc)
            await self.collection.insert_one(doc)

            add_span_attributes(
                **{
                    str(EventAttributes.EVENT_TYPE): str(event.event_type),
                    str(EventAttributes.EVENT_ID): event.event_id,
                    str(EventAttributes.EXECUTION_ID): event.aggregate_id or "",
                }
            )

            duration = asyncio.get_event_loop().time() - start
            self.metrics.record_event_store_duration(duration, "store_single", self.collection_name)
            self.metrics.record_event_stored(event.event_type, self.collection_name)
            return True
        except DuplicateKeyError:
            logger.warning(f"Event {event.event_id} already exists")
            return True
        except Exception as e:
            logger.error(f"Failed to store event {event.event_id}: {e.__class__.__name__}: {e}", exc_info=True)
            self.metrics.record_event_store_failed(event.event_type, type(e).__name__)
            return False

    async def store_batch(self, events: List[BaseEvent]) -> Dict[str, int]:
        start = asyncio.get_event_loop().time()
        results = {"total": len(events), "stored": 0, "duplicates": 0, "failed": 0}
        if not events:
            return results

        try:
            docs = []
            now = datetime.now(timezone.utc)
            for e in events:
                d = e.model_dump()
                d["stored_at"] = now
                docs.append(d)

            try:
                res = await self.collection.insert_many(docs, ordered=False)
                results["stored"] = len(res.inserted_ids)
            except Exception as e:
                if isinstance(e, BulkWriteError) and e.details:
                    errs = e.details.get("writeErrors", [])
                    for err in errs:
                        if err.get("code") == 11000:
                            results["duplicates"] += 1
                        else:
                            results["failed"] += 1
                    results["stored"] = results["total"] - results["duplicates"] - results["failed"]
                else:
                    raise

            duration = asyncio.get_event_loop().time() - start
            self.metrics.record_event_store_duration(duration, "store_batch", self.collection_name)
            add_span_attributes(**{"events.batch.count": len(events)})
            if results["stored"] > 0:
                for event in events:
                    self.metrics.record_event_stored(event.event_type, self.collection_name)
            return results
        except Exception as e:
            logger.error(f"Failed to store batch: {e.__class__.__name__}: {e}", exc_info=True)
            results["failed"] = results["total"] - results["stored"]
            return results

    async def get_event(self, event_id: str) -> BaseEvent | None:
        start = asyncio.get_event_loop().time()
        doc = await self.collection.find_one({"event_id": event_id}, self._PROJECTION)
        if not doc:
            return None
        event = self.schema_registry.deserialize_json(doc)

        duration = asyncio.get_event_loop().time() - start
        self.metrics.record_event_query_duration(duration, "get_by_id", self.collection_name)
        return event

    async def get_events_by_type(
        self,
        event_type: EventType,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[BaseEvent]:
        start = asyncio.get_event_loop().time()
        q: Dict[str, Any] = {"event_type": str(event_type)}
        if tr := self._time_range(start_time, end_time):
            q["timestamp"] = tr

        events = await self._find_events(q, sort=("timestamp", DESCENDING), limit=limit, offset=offset)

        duration = asyncio.get_event_loop().time() - start
        self.metrics.record_event_query_duration(duration, "get_by_type", self.collection_name)
        return events

    async def get_execution_events(
        self,
        execution_id: str,
        event_types: List[EventType] | None = None,
    ) -> List[BaseEvent]:
        start = asyncio.get_event_loop().time()
        q: Dict[str, Any] = {"execution_id": execution_id}
        if event_types:
            q["event_type"] = {"$in": [str(et) for et in event_types]}

        events = await self._find_events(q, sort=("timestamp", ASCENDING))

        duration = asyncio.get_event_loop().time() - start
        self.metrics.record_event_query_duration(duration, "get_execution_events", self.collection_name)
        return events

    async def get_user_events(
        self,
        user_id: str,
        event_types: List[EventType] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> List[BaseEvent]:
        start = asyncio.get_event_loop().time()
        q: Dict[str, Any] = {"metadata.user_id": str(user_id)}
        if event_types:
            q["event_type"] = {"$in": event_types}
        if tr := self._time_range(start_time, end_time):
            q["timestamp"] = tr

        events = await self._find_events(q, sort=("timestamp", DESCENDING), limit=limit)

        duration = asyncio.get_event_loop().time() - start
        self.metrics.record_event_query_duration(duration, "get_user_events", self.collection_name)
        return events

    async def get_security_events(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        user_id: str | None = None,
        limit: int = 100,
    ) -> List[BaseEvent]:
        start = asyncio.get_event_loop().time()
        q: Dict[str, Any] = {"event_type": {"$in": self._SECURITY_TYPES}}
        if user_id:
            q["metadata.user_id"] = str(user_id)
        if tr := self._time_range(start_time, end_time):
            q["timestamp"] = tr

        events = await self._find_events(q, sort=("timestamp", DESCENDING), limit=limit)

        duration = asyncio.get_event_loop().time() - start
        self.metrics.record_event_query_duration(duration, "get_security_events", self.collection_name)
        return events

    async def get_correlation_chain(self, correlation_id: str) -> List[BaseEvent]:
        start = asyncio.get_event_loop().time()
        q = {"metadata.correlation_id": str(correlation_id)}
        events = await self._find_events(q, sort=("timestamp", ASCENDING))

        duration = asyncio.get_event_loop().time() - start
        self.metrics.record_event_query_duration(duration, "get_correlation_chain", self.collection_name)
        return events

    async def replay_events(
        self,
        start_time: datetime,
        end_time: datetime | None = None,
        event_types: List[EventType] | None = None,
        callback: Callable[[BaseEvent], Awaitable[None]] | None = None,
    ) -> int:
        start = asyncio.get_event_loop().time()
        count = 0

        try:
            q: Dict[str, Any] = {"timestamp": {"$gte": start_time}}
            if end_time:
                q["timestamp"]["$lte"] = end_time
            if event_types:
                q["event_type"] = {"$in": [str(et) for et in event_types]}

            cursor = self.collection.find(q, self._PROJECTION).sort("timestamp", ASCENDING)
            async for doc in cursor:
                event = self.schema_registry.deserialize_json(doc)
                if callback:
                    await callback(event)
                count += 1

            duration = asyncio.get_event_loop().time() - start
            self.metrics.record_event_query_duration(duration, "replay_events", self.collection_name)
            logger.info(f"Replayed {count} events from {start_time} to {end_time}")
            return count
        except Exception as e:
            logger.error(f"Failed to replay events: {e}")
            return count

    async def get_event_stats(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> Dict[str, Any]:
        pipeline: List[Dict[str, Any]] = []
        if start_time or end_time:
            match: Dict[str, Any] = {}
            if start_time:
                match["timestamp"] = {"$gte": start_time}
            if end_time:
                match.setdefault("timestamp", {})["$lte"] = end_time
            pipeline.append({"$match": match})

        pipeline.extend(
            [
                {
                    "$group": {
                        "_id": "$event_type",
                        "count": {"$sum": 1},
                        "first_event": {"$min": "$timestamp"},
                        "last_event": {"$max": "$timestamp"},
                    }
                },
                {"$sort": {"count": -1}},
            ]
        )

        cursor = await self.collection.aggregate(pipeline)
        stats: Dict[str, Any] = {"total_events": 0, "event_types": {}, "start_time": start_time, "end_time": end_time}
        async for r in cursor:
            et = r["_id"]
            c = r["count"]
            stats["event_types"][et] = {
                "count": c,
                "first_event": r["first_event"],
                "last_event": r["last_event"],
            }
            stats["total_events"] += c
        return stats

    async def _deserialize_cursor(self, cursor: Cursor) -> list[BaseEvent]:
        return [self.schema_registry.deserialize_json(doc) async for doc in cursor]

    def _time_range(self, start_time: datetime | None, end_time: datetime | None) -> Dict[str, Any] | None:
        if not start_time and not end_time:
            return None
        tr: Dict[str, Any] = {}
        if start_time:
            tr["$gte"] = start_time
        if end_time:
            tr["$lte"] = end_time
        return tr

    async def _find_events(
        self,
        query: Dict[str, Any],
        *,
        sort: tuple[str, int],
        limit: int | None = None,
        offset: int = 0,
    ) -> List[BaseEvent]:
        cur = self.collection.find(query, self._PROJECTION).sort(*sort).skip(offset)
        if limit is not None:
            cur = cur.limit(limit)
        return await self._deserialize_cursor(cur)

    async def health_check(self) -> Dict[str, Any]:
        try:
            await self.db.command("ping")
            event_count = await self.collection.count_documents({})
            return {
                "healthy": True,
                "event_count": event_count,
                "collection": self.collection_name,
                "initialized": self._initialized,
            }
        except Exception as e:
            logger.error(f"Event store health check failed: {e}")
            return {"healthy": False, "error": str(e)}


def create_event_store(
    db: Database,
    schema_registry: SchemaRegistryManager,
    collection_name: str = "events",
    ttl_days: int = 90,
    batch_size: int = 100,
) -> EventStore:
    return EventStore(
        db=db,
        schema_registry=schema_registry,
        collection_name=collection_name,
        ttl_days=ttl_days,
        batch_size=batch_size,
    )
