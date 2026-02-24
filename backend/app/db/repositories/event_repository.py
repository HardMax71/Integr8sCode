import time
from datetime import datetime, timezone
from typing import Any, Mapping

import structlog
from beanie.odm.enums import SortDirection
from beanie.odm.operators.find import BaseFindOperator
from beanie.operators import GTE, LTE, Eq, In, Not, Or, RegEx
from monggregate import Pipeline, S
from opentelemetry import trace
from pymongo.errors import DuplicateKeyError

from app.core.metrics import DatabaseMetrics
from app.db.docs import EventArchiveDocument, EventDocument
from app.domain.enums import EventType
from app.domain.events import (
    ArchivedEvent,
    DomainEvent,
    DomainEventAdapter,
    EventListResult,
    EventReplayInfo,
    EventStatistics,
    EventTypeCount,
    ServiceEventCount,
)


class EventRepository:
    def __init__(self, logger: structlog.stdlib.BoundLogger, database_metrics: DatabaseMetrics) -> None:
        self.logger = logger
        self.metrics = database_metrics

    def _time_conditions(self, start_time: datetime | None, end_time: datetime | None) -> list[Any]:
        """Build time range conditions for queries."""
        conditions = [
            GTE(EventDocument.timestamp, start_time) if start_time else None,
            LTE(EventDocument.timestamp, end_time) if end_time else None,
        ]
        return [c for c in conditions if c is not None]

    def _build_time_filter(self, start_time: datetime | None, end_time: datetime | None) -> dict[str, object]:
        """Build time filter dict for aggregation pipelines."""
        return {key: value for key, value in {"$gte": start_time, "$lte": end_time}.items() if value is not None}

    async def store_event(self, event: DomainEvent) -> str:
        """Idempotent event store — silently ignores duplicates by event_id."""
        start = time.monotonic()
        data = event.model_dump(exclude_none=True)
        data.setdefault("stored_at", datetime.now(timezone.utc))
        doc = EventDocument(**data)
        trace.get_current_span().set_attributes({
            "event.type": event.event_type,
            "event.id": event.event_id,
            "execution.id": event.aggregate_id or "",
        })
        try:
            await doc.insert()
        except DuplicateKeyError:
            self.logger.debug(f"Event {event.event_id} already stored, skipping")
            duration = time.monotonic() - start
            self.metrics.record_mongodb_operation("store", "duplicate")
            self.metrics.record_mongodb_query_duration(duration, "store")
            return event.event_id
        duration = time.monotonic() - start
        self.metrics.record_mongodb_operation("store", "success")
        self.metrics.record_mongodb_query_duration(duration, "store")
        self.metrics.record_event_store_duration(duration, "store", "events")
        self.logger.debug(f"Stored event {event.event_id} of type {event.event_type}")
        return event.event_id

    async def get_event(self, event_id: str) -> DomainEvent | None:
        start = time.monotonic()
        doc = await EventDocument.find_one(EventDocument.event_id == event_id)
        duration = time.monotonic() - start
        self.metrics.record_mongodb_operation("find_one", "success" if doc else "not_found")
        self.metrics.record_mongodb_query_duration(duration, "find_one")
        if not doc:
            return None
        return DomainEventAdapter.validate_python(doc)

    async def get_events_by_aggregate(
            self, aggregate_id: str, event_types: list[EventType] | None = None, limit: int = 100
    ) -> list[DomainEvent]:
        start = time.monotonic()
        conditions: list[BaseFindOperator] = [Eq(EventDocument.aggregate_id, aggregate_id)]
        if event_types:
            conditions.append(In(EventDocument.event_type, event_types))
        docs = (
            await EventDocument.find(*conditions).sort([("timestamp", SortDirection.ASCENDING)]).limit(limit).to_list()
        )
        duration = time.monotonic() - start
        self.metrics.record_mongodb_operation("find_by_aggregate", "success")
        self.metrics.record_mongodb_query_duration(duration, "find_by_aggregate")
        return [DomainEventAdapter.validate_python(d) for d in docs]

    async def get_execution_events(
            self,
            execution_id: str,
            limit: int = 100,
            skip: int = 0,
            exclude_system_events: bool = False,
            event_types: list[EventType] | None = None,
    ) -> EventListResult:
        start = time.monotonic()
        conditions: list[Any] = [
            Or(
                EventDocument.execution_id == execution_id,
                EventDocument.aggregate_id == execution_id,
            ),
            In(EventDocument.event_type, event_types) if event_types else None,
            Not(RegEx(EventDocument.metadata.service_name, "^system-")) if exclude_system_events else None,
        ]
        conditions = [c for c in conditions if c is not None]
        # Fetch before count: avoids race where a doc inserted between count→fetch
        # makes total < len(events).
        docs = (
            await EventDocument.find(*conditions)
            .sort([("timestamp", SortDirection.ASCENDING)])
            .skip(skip).limit(limit).to_list()
        )
        events = [DomainEventAdapter.validate_python(d) for d in docs]
        total_count = await EventDocument.find(*conditions).count()
        total_count = max(total_count, skip + len(events))
        duration = time.monotonic() - start
        self.metrics.record_mongodb_operation("find_execution_events", "success")
        self.metrics.record_mongodb_query_duration(duration, "find_execution_events")
        return EventListResult(
            events=events,
            total=total_count,
            skip=skip,
            limit=limit,
            has_more=(skip + limit) < total_count,
        )

    async def get_event_statistics(
            self,
            start_time: datetime | None = None,
            end_time: datetime | None = None,
            match: dict[str, object] | None = None,
    ) -> EventStatistics:
        start = time.monotonic()
        pipeline: list[Mapping[str, object]] = []
        if match:
            pipeline.append({"$match": match})
        time_filter = self._build_time_filter(start_time, end_time)
        if time_filter:
            pipeline.append({"$match": {"timestamp": time_filter}})

        pipeline.extend(
            [
                {
                    "$facet": {
                        "by_type": [
                            {"$group": {"_id": S.field(EventDocument.event_type), "count": {"$sum": 1}}},
                            {"$sort": {"count": -1}},
                        ],
                        "by_service": [
                            {"$group": {"_id": S.field(EventDocument.metadata.service_name), "count": {"$sum": 1}}},
                            {"$sort": {"count": -1}},
                        ],
                        "by_hour": [
                            {
                                "$group": {
                                    "_id": {
                                        "$dateToString": {
                                            "format": "%Y-%m-%d %H:00",
                                            "date": S.field(EventDocument.timestamp),
                                        }
                                    },
                                    "count": {"$sum": 1},
                                }
                            },
                            {"$sort": {"_id": 1}},
                        ],
                        "total": [{"$count": "count"}],
                    }
                },
                {
                    "$project": {
                        "_id": 0,
                        "total_events": {"$ifNull": [{"$arrayElemAt": ["$total.count", 0]}, 0]},
                        "events_by_type": {
                            "$arrayToObject": {
                                "$map": {"input": "$by_type", "as": "t", "in": {"k": "$$t._id", "v": "$$t.count"}}
                            }
                        },
                        "events_by_service": {
                            "$arrayToObject": {
                                "$map": {"input": "$by_service", "as": "s", "in": {"k": "$$s._id", "v": "$$s.count"}}
                            }
                        },
                        "events_by_hour": {
                            "$map": {
                                "input": "$by_hour",
                                "as": "h",
                                "in": {"hour": "$$h._id", "count": "$$h.count"},
                            }
                        },
                    }
                },
            ]
        )

        async for doc in EventDocument.aggregate(pipeline):
            doc["events_by_type"] = [
                EventTypeCount(event_type=EventType(k), count=v)
                for k, v in doc.get("events_by_type", {}).items()
            ]
            doc["events_by_service"] = [
                ServiceEventCount(service_name=k, count=v)
                for k, v in doc.get("events_by_service", {}).items()
            ]
            duration = time.monotonic() - start
            self.metrics.record_mongodb_operation("aggregate_statistics", "success")
            self.metrics.record_mongodb_query_duration(duration, "aggregate_statistics")
            return EventStatistics(**doc)

        duration = time.monotonic() - start
        self.metrics.record_mongodb_operation("aggregate_statistics", "empty")
        self.metrics.record_mongodb_query_duration(duration, "aggregate_statistics")
        return EventStatistics(total_events=0, events_by_type=[], events_by_service=[], events_by_hour=[])

    async def get_user_events_paginated(
            self,
            user_id: str,
            event_types: list[EventType] | None = None,
            start_time: datetime | None = None,
            end_time: datetime | None = None,
            limit: int = 100,
            skip: int = 0,
            sort_order: str = "desc",
    ) -> EventListResult:
        start = time.monotonic()
        conditions = [
            EventDocument.metadata.user_id == user_id,
            In(EventDocument.event_type, event_types) if event_types else None,
            *self._time_conditions(start_time, end_time),
        ]
        conditions = [c for c in conditions if c is not None]

        sort_direction = SortDirection.DESCENDING if sort_order == "desc" else SortDirection.ASCENDING
        docs = (
            await EventDocument.find(*conditions)
            .sort([("timestamp", sort_direction)])
            .skip(skip).limit(limit).to_list()
        )
        events = [DomainEventAdapter.validate_python(d) for d in docs]
        total_count = await EventDocument.find(*conditions).count()
        total_count = max(total_count, skip + len(events))
        duration = time.monotonic() - start
        self.metrics.record_mongodb_operation("find_user_events", "success")
        self.metrics.record_mongodb_query_duration(duration, "find_user_events")
        return EventListResult(
            events=events,
            total=total_count,
            skip=skip,
            limit=limit,
            has_more=(skip + limit) < total_count,
        )

    async def count_events(self, *conditions: Any) -> int:
        start = time.monotonic()
        result = await EventDocument.find(*conditions).count()
        duration = time.monotonic() - start
        self.metrics.record_mongodb_operation("count", "success")
        self.metrics.record_mongodb_query_duration(duration, "count")
        return result

    async def query_events(
            self,
            query: dict[str, Any],
            sort_field: str = "timestamp",
            skip: int = 0,
            limit: int = 100,
    ) -> EventListResult:
        """Query events with filter, sort, and pagination. Always sorts descending (newest first)."""
        start = time.monotonic()
        docs = (
            await EventDocument.find(query)
            .sort([(sort_field, SortDirection.DESCENDING)])
            .skip(skip).limit(limit).to_list()
        )
        events = [DomainEventAdapter.validate_python(d) for d in docs]
        total_count = await EventDocument.find(query).count()
        total_count = max(total_count, skip + len(events))
        duration = time.monotonic() - start
        self.metrics.record_mongodb_operation("query_events", "success")
        self.metrics.record_mongodb_query_duration(duration, "query_events")
        return EventListResult(
            events=events, total=total_count, skip=skip, limit=limit, has_more=(skip + limit) < total_count
        )

    async def delete_event_with_archival(
            self, event_id: str, deleted_by: str, deletion_reason: str = "Admin deletion via API"
    ) -> ArchivedEvent | None:
        start = time.monotonic()
        doc = await EventDocument.find_one(EventDocument.event_id == event_id)
        if not doc:
            duration = time.monotonic() - start
            self.metrics.record_mongodb_operation("delete_with_archival", "not_found")
            self.metrics.record_mongodb_query_duration(duration, "delete_with_archival")
            return None

        deleted_at = datetime.now(timezone.utc)
        archive_fields = {"deleted_at": deleted_at, "deleted_by": deleted_by, "deletion_reason": deletion_reason}
        archived_doc = EventArchiveDocument.model_validate(doc).model_copy(update=archive_fields)
        await archived_doc.insert()
        await doc.delete()
        duration = time.monotonic() - start
        self.metrics.record_mongodb_operation("delete_with_archival", "success")
        self.metrics.record_mongodb_query_duration(duration, "delete_with_archival")
        return ArchivedEvent.model_validate(doc).model_copy(update=archive_fields)

    async def get_aggregate_replay_info(self, aggregate_id: str) -> EventReplayInfo | None:
        start = time.monotonic()
        # Match on both aggregate_id and execution_id (consistent with get_execution_events)
        pipeline = (
            Pipeline()
            .match({"$or": [{EventDocument.aggregate_id: aggregate_id}, {EventDocument.execution_id: aggregate_id}]})
            .sort(by=EventDocument.timestamp)
            .group(
                by=None,
                query={
                    "events": {"$push": "$$ROOT"},
                    "event_count": S.sum(1),
                    "event_types": {"$addToSet": S.field(EventDocument.event_type)},
                    "start_time": S.min(S.field(EventDocument.timestamp)),
                    "end_time": S.max(S.field(EventDocument.timestamp)),
                },
            )
            .project(_id=0)
        )

        async for doc in EventDocument.aggregate(pipeline.export()):
            events = [DomainEventAdapter.validate_python(e) for e in doc["events"]]
            duration = time.monotonic() - start
            self.metrics.record_mongodb_operation("aggregate_replay_info", "success")
            self.metrics.record_mongodb_query_duration(duration, "aggregate_replay_info")
            return EventReplayInfo(
                events=events,
                event_count=doc["event_count"],
                event_types=doc["event_types"],
                start_time=doc["start_time"],
                end_time=doc["end_time"],
            )

        duration = time.monotonic() - start
        self.metrics.record_mongodb_operation("aggregate_replay_info", "empty")
        self.metrics.record_mongodb_query_duration(duration, "aggregate_replay_info")
        return None
