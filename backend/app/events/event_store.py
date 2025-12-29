import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Dict, List

from beanie.odm.enums import SortDirection
from pymongo.errors import BulkWriteError, DuplicateKeyError

from app.core.metrics.context import get_event_metrics
from app.core.tracing import EventAttributes
from app.core.tracing.utils import add_span_attributes
from app.db.docs import EventStoreDocument
from app.domain.enums.events import EventType
from app.domain.events.event_metadata import EventMetadata
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.base import BaseEvent


class EventStore:
    def __init__(
        self,
        schema_registry: SchemaRegistryManager,
        logger: logging.Logger,
        ttl_days: int = 90,
        batch_size: int = 100,
    ):
        self.metrics = get_event_metrics()
        self.schema_registry = schema_registry
        self.logger = logger
        self.ttl_days = ttl_days
        self.batch_size = batch_size
        self._initialized = False

        self._PROJECTION = {"stored_at": 0, "_id": 0}
        self._SECURITY_TYPES = [
            EventType.USER_LOGIN,
            EventType.USER_LOGGED_OUT,
            EventType.SECURITY_VIOLATION,
        ]

    async def initialize(self) -> None:
        if self._initialized:
            return
        # Beanie handles index creation via Document.Settings.indexes
        self._initialized = True
        self.logger.info("Event store initialized with Beanie")

    def _event_to_doc(self, event: BaseEvent) -> EventStoreDocument:
        """Convert BaseEvent to EventStoreDocument."""
        event_dict = event.model_dump()
        metadata_dict = event_dict.pop("metadata", {})
        metadata = EventMetadata(**metadata_dict)

        return EventStoreDocument(
            event_id=event.event_id,
            event_type=event.event_type,
            event_version=event.event_version,
            timestamp=event.timestamp,
            aggregate_id=event.aggregate_id,
            metadata=metadata,
            stored_at=datetime.now(timezone.utc),
            **{
                k: v
                for k, v in event_dict.items()
                if k not in {"event_id", "event_type", "event_version", "timestamp", "aggregate_id"}
            },
        )

    def _doc_to_dict(self, doc: EventStoreDocument) -> Dict[str, Any]:
        """Convert EventStoreDocument to dict for schema_registry deserialization."""
        result: Dict[str, Any] = doc.model_dump(exclude={"id", "revision_id", "stored_at"})
        # Ensure metadata is a dict for schema_registry
        if isinstance(result.get("metadata"), dict):
            pass  # Already a dict
        elif hasattr(result.get("metadata"), "model_dump"):
            result["metadata"] = result["metadata"].model_dump()
        return result

    async def store_event(self, event: BaseEvent) -> bool:
        start = asyncio.get_event_loop().time()
        try:
            doc = self._event_to_doc(event)
            await doc.insert()

            add_span_attributes(
                **{
                    str(EventAttributes.EVENT_TYPE): str(event.event_type),
                    str(EventAttributes.EVENT_ID): event.event_id,
                    str(EventAttributes.EXECUTION_ID): event.aggregate_id or "",
                }
            )

            duration = asyncio.get_event_loop().time() - start
            self.metrics.record_event_store_duration(duration, "store_single", "event_store")
            self.metrics.record_event_stored(event.event_type, "event_store")
            return True
        except DuplicateKeyError:
            self.logger.warning(f"Event {event.event_id} already exists")
            return True
        except Exception as e:
            self.logger.error(f"Failed to store event {event.event_id}: {e.__class__.__name__}: {e}", exc_info=True)
            self.metrics.record_event_store_failed(event.event_type, type(e).__name__)
            return False

    async def store_batch(self, events: List[BaseEvent]) -> Dict[str, int]:
        start = asyncio.get_event_loop().time()
        results = {"total": len(events), "stored": 0, "duplicates": 0, "failed": 0}
        if not events:
            return results

        try:
            docs = [self._event_to_doc(e) for e in events]

            try:
                await EventStoreDocument.insert_many(docs)
                results["stored"] = len(docs)
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
            self.metrics.record_event_store_duration(duration, "store_batch", "event_store")
            add_span_attributes(**{"events.batch.count": len(events)})
            if results["stored"] > 0:
                for event in events:
                    self.metrics.record_event_stored(event.event_type, "event_store")
            return results
        except Exception as e:
            self.logger.error(f"Failed to store batch: {e.__class__.__name__}: {e}", exc_info=True)
            results["failed"] = results["total"] - results["stored"]
            return results

    async def get_event(self, event_id: str) -> BaseEvent | None:
        start = asyncio.get_event_loop().time()
        doc = await EventStoreDocument.find_one({"event_id": event_id})
        if not doc:
            return None

        event_dict = self._doc_to_dict(doc)
        event = self.schema_registry.deserialize_json(event_dict)

        duration = asyncio.get_event_loop().time() - start
        self.metrics.record_event_query_duration(duration, "get_by_id", "event_store")
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
        query: Dict[str, Any] = {"event_type": event_type}
        if tr := self._time_range(start_time, end_time):
            query["timestamp"] = tr

        docs = await (
            EventStoreDocument.find(query)
            .sort([("timestamp", SortDirection.DESCENDING)])
            .skip(offset)
            .limit(limit)
            .to_list()
        )
        events = [self.schema_registry.deserialize_json(self._doc_to_dict(d)) for d in docs]

        duration = asyncio.get_event_loop().time() - start
        self.metrics.record_event_query_duration(duration, "get_by_type", "event_store")
        return events

    async def get_execution_events(
        self,
        execution_id: str,
        event_types: List[EventType] | None = None,
    ) -> List[BaseEvent]:
        start = asyncio.get_event_loop().time()
        query: Dict[str, Any] = {"execution_id": execution_id}
        if event_types:
            query["event_type"] = {"$in": event_types}

        docs = await EventStoreDocument.find(query).sort([("timestamp", SortDirection.ASCENDING)]).to_list()
        events = [self.schema_registry.deserialize_json(self._doc_to_dict(d)) for d in docs]

        duration = asyncio.get_event_loop().time() - start
        self.metrics.record_event_query_duration(duration, "get_execution_events", "event_store")
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
        query: Dict[str, Any] = {"metadata.user_id": str(user_id)}
        if event_types:
            query["event_type"] = {"$in": event_types}
        if tr := self._time_range(start_time, end_time):
            query["timestamp"] = tr

        docs = (
            await EventStoreDocument.find(query).sort([("timestamp", SortDirection.DESCENDING)]).limit(limit).to_list()
        )
        events = [self.schema_registry.deserialize_json(self._doc_to_dict(d)) for d in docs]

        duration = asyncio.get_event_loop().time() - start
        self.metrics.record_event_query_duration(duration, "get_user_events", "event_store")
        return events

    async def get_security_events(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        user_id: str | None = None,
        limit: int = 100,
    ) -> List[BaseEvent]:
        start = asyncio.get_event_loop().time()
        query: Dict[str, Any] = {"event_type": {"$in": self._SECURITY_TYPES}}
        if user_id:
            query["metadata.user_id"] = str(user_id)
        if tr := self._time_range(start_time, end_time):
            query["timestamp"] = tr

        docs = (
            await EventStoreDocument.find(query).sort([("timestamp", SortDirection.DESCENDING)]).limit(limit).to_list()
        )
        events = [self.schema_registry.deserialize_json(self._doc_to_dict(d)) for d in docs]

        duration = asyncio.get_event_loop().time() - start
        self.metrics.record_event_query_duration(duration, "get_security_events", "event_store")
        return events

    async def get_correlation_chain(self, correlation_id: str) -> List[BaseEvent]:
        start = asyncio.get_event_loop().time()
        docs = await (
            EventStoreDocument.find({"metadata.correlation_id": str(correlation_id)})
            .sort([("timestamp", SortDirection.ASCENDING)])
            .to_list()
        )
        events = [self.schema_registry.deserialize_json(self._doc_to_dict(d)) for d in docs]

        duration = asyncio.get_event_loop().time() - start
        self.metrics.record_event_query_duration(duration, "get_correlation_chain", "event_store")
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
            query: Dict[str, Any] = {"timestamp": {"$gte": start_time}}
            if end_time:
                query["timestamp"]["$lte"] = end_time
            if event_types:
                query["event_type"] = {"$in": event_types}

            async for doc in EventStoreDocument.find(query).sort([("timestamp", SortDirection.ASCENDING)]):
                event_dict = self._doc_to_dict(doc)
                event = self.schema_registry.deserialize_json(event_dict)
                if callback:
                    await callback(event)
                count += 1

            duration = asyncio.get_event_loop().time() - start
            self.metrics.record_event_query_duration(duration, "replay_events", "event_store")
            self.logger.info(f"Replayed {count} events from {start_time} to {end_time}")
            return count
        except Exception as e:
            self.logger.error(f"Failed to replay events: {e}")
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

        stats: Dict[str, Any] = {"total_events": 0, "event_types": {}, "start_time": start_time, "end_time": end_time}
        async for r in EventStoreDocument.aggregate(pipeline):
            et = r["_id"]
            c = r["count"]
            stats["event_types"][et] = {
                "count": c,
                "first_event": r["first_event"],
                "last_event": r["last_event"],
            }
            stats["total_events"] += c
        return stats

    def _time_range(self, start_time: datetime | None, end_time: datetime | None) -> Dict[str, Any] | None:
        if not start_time and not end_time:
            return None
        tr: Dict[str, Any] = {}
        if start_time:
            tr["$gte"] = start_time
        if end_time:
            tr["$lte"] = end_time
        return tr

    async def health_check(self) -> Dict[str, Any]:
        try:
            event_count = await EventStoreDocument.count()
            return {
                "healthy": True,
                "event_count": event_count,
                "collection": "event_store",
                "initialized": self._initialized,
            }
        except Exception as e:
            self.logger.error(f"Event store health check failed: {e}")
            return {"healthy": False, "error": str(e)}


def create_event_store(
    schema_registry: SchemaRegistryManager,
    logger: logging.Logger,
    ttl_days: int = 90,
    batch_size: int = 100,
) -> EventStore:
    return EventStore(
        schema_registry=schema_registry,
        logger=logger,
        ttl_days=ttl_days,
        batch_size=batch_size,
    )
