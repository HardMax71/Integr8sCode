import logging
from dataclasses import asdict, fields
from datetime import datetime, timezone
from typing import Any, Mapping

from beanie.odm.enums import SortDirection
from beanie.operators import GTE, LTE, In, Not, Or, RegEx

from app.core.tracing import EventAttributes
from app.core.tracing.utils import add_span_attributes
from app.db.docs import EventArchiveDocument, EventDocument
from app.domain.enums.events import EventType
from app.domain.events import Event
from app.domain.events.event_models import (
    ArchivedEvent,
    EventAggregationResult,
    EventListResult,
    EventReplayInfo,
    EventStatistics,
)


class EventRepository:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

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

    async def store_event(self, event: Event) -> str:
        data = asdict(event)
        if not data.get("stored_at"):
            data["stored_at"] = datetime.now(timezone.utc)
        # Remove None values so EventDocument defaults can apply (e.g., ttl_expires_at)
        data = {k: v for k, v in data.items() if v is not None}

        doc = EventDocument(**data)
        add_span_attributes(
            **{
                str(EventAttributes.EVENT_TYPE): str(event.event_type),
                str(EventAttributes.EVENT_ID): event.event_id,
                str(EventAttributes.EXECUTION_ID): event.aggregate_id or "",
            }
        )
        await doc.insert()
        self.logger.debug(f"Stored event {event.event_id} of type {event.event_type}")
        return event.event_id

    async def get_event(self, event_id: str) -> Event | None:
        doc = await EventDocument.find_one({"event_id": event_id})
        if not doc:
            return None
        return Event(**doc.model_dump(exclude={"id", "revision_id"}))

    async def get_events_by_aggregate(
        self, aggregate_id: str, event_types: list[EventType] | None = None, limit: int = 100
    ) -> list[Event]:
        conditions = [
            EventDocument.aggregate_id == aggregate_id,
            In(EventDocument.event_type, [t.value for t in event_types]) if event_types else None,
        ]
        conditions = [c for c in conditions if c is not None]
        docs = (
            await EventDocument.find(*conditions).sort([("timestamp", SortDirection.ASCENDING)]).limit(limit).to_list()
        )
        return [Event(**d.model_dump(exclude={"id", "revision_id"})) for d in docs]

    async def get_events_by_correlation(self, correlation_id: str, limit: int = 100, skip: int = 0) -> EventListResult:
        query = EventDocument.find(EventDocument.metadata.correlation_id == correlation_id)
        total_count = await query.count()
        docs = await query.sort([("timestamp", SortDirection.ASCENDING)]).skip(skip).limit(limit).to_list()
        events = [Event(**d.model_dump(exclude={"id", "revision_id"})) for d in docs]
        return EventListResult(
            events=events,
            total=total_count,
            skip=skip,
            limit=limit,
            has_more=(skip + limit) < total_count,
        )

    async def get_execution_events(
        self, execution_id: str, limit: int = 100, skip: int = 0, exclude_system_events: bool = False
    ) -> EventListResult:
        conditions: list[Any] = [
            Or(
                EventDocument.payload["execution_id"] == execution_id,
                EventDocument.aggregate_id == execution_id,
            ),
            Not(RegEx(EventDocument.metadata.service_name, "^system-")) if exclude_system_events else None,
        ]
        conditions = [c for c in conditions if c is not None]
        query = EventDocument.find(*conditions)
        total_count = await query.count()
        docs = await query.sort([("timestamp", SortDirection.ASCENDING)]).skip(skip).limit(limit).to_list()
        events = [Event(**d.model_dump(exclude={"id", "revision_id"})) for d in docs]
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
                            {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
                            {"$sort": {"count": -1}},
                        ],
                        "by_service": [
                            {"$group": {"_id": "$metadata.service_name", "count": {"$sum": 1}}},
                            {"$sort": {"count": -1}},
                        ],
                        "by_hour": [
                            {
                                "$group": {
                                    "_id": {"$dateToString": {"format": "%Y-%m-%d %H:00", "date": "$timestamp"}},
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
            return EventStatistics(**doc)

        return EventStatistics(total_events=0, events_by_type={}, events_by_service={}, events_by_hour=[])

    async def get_user_events_paginated(
        self,
        user_id: str,
        event_types: list[str] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        skip: int = 0,
        sort_order: str = "desc",
    ) -> EventListResult:
        conditions = [
            EventDocument.metadata.user_id == user_id,
            In(EventDocument.event_type, event_types) if event_types else None,
            *self._time_conditions(start_time, end_time),
        ]
        conditions = [c for c in conditions if c is not None]

        query = EventDocument.find(*conditions)
        total_count = await query.count()
        sort_direction = SortDirection.DESCENDING if sort_order == "desc" else SortDirection.ASCENDING
        docs = await query.sort([("timestamp", sort_direction)]).skip(skip).limit(limit).to_list()
        events = [Event(**d.model_dump(exclude={"id", "revision_id"})) for d in docs]
        return EventListResult(
            events=events,
            total=total_count,
            skip=skip,
            limit=limit,
            has_more=(skip + limit) < total_count,
        )

    async def query_events(
        self,
        query: dict[str, Any],
        sort_field: str = "timestamp",
        skip: int = 0,
        limit: int = 100,
    ) -> EventListResult:
        """Query events with filter, sort, and pagination. Always sorts descending (newest first)."""
        cursor = EventDocument.find(query)
        total_count = await cursor.count()
        docs = await cursor.sort([(sort_field, SortDirection.DESCENDING)]).skip(skip).limit(limit).to_list()
        events = [Event(**d.model_dump(exclude={"id", "revision_id"})) for d in docs]
        return EventListResult(
            events=events, total=total_count, skip=skip, limit=limit, has_more=(skip + limit) < total_count
        )

    async def aggregate_events(self, pipeline: list[dict[str, Any]], limit: int = 100) -> EventAggregationResult:
        """Run aggregation pipeline on events."""
        pipeline_with_limit = [*pipeline, {"$limit": limit}]
        results = await EventDocument.aggregate(pipeline_with_limit).to_list()
        return EventAggregationResult(results=results, pipeline=pipeline_with_limit)

    async def list_event_types(self, match: dict[str, object] | None = None) -> list[str]:
        """List distinct event types, optionally filtered."""
        pipeline: list[dict[str, object]] = []
        if match:
            pipeline.append({"$match": match})
        pipeline.extend(
            [
                {"$group": {"_id": "$event_type"}},
                {"$sort": {"_id": 1}},
            ]
        )
        results: list[dict[str, str]] = await EventDocument.aggregate(pipeline).to_list()
        return [doc["_id"] for doc in results if doc.get("_id")]

    async def delete_event_with_archival(
        self, event_id: str, deleted_by: str, deletion_reason: str = "Admin deletion via API"
    ) -> ArchivedEvent | None:
        doc = await EventDocument.find_one({"event_id": event_id})
        if not doc:
            return None

        deleted_at = datetime.now(timezone.utc)
        archived_doc = EventArchiveDocument(
            **doc.model_dump(exclude={"id", "revision_id"}),
            deleted_at=deleted_at,
            deleted_by=deleted_by,
            deletion_reason=deletion_reason,
        )
        await archived_doc.insert()
        await doc.delete()
        return ArchivedEvent(
            **doc.model_dump(exclude={"id", "revision_id"}),
            deleted_at=deleted_at,
            deleted_by=deleted_by,
            deletion_reason=deletion_reason,
        )

    async def get_aggregate_replay_info(self, aggregate_id: str) -> EventReplayInfo | None:
        pipeline = [
            {"$match": {"aggregate_id": aggregate_id}},
            {"$sort": {"timestamp": 1}},
            {
                "$group": {
                    "_id": None,
                    "events": {"$push": "$$ROOT"},
                    "event_count": {"$sum": 1},
                    "event_types": {"$addToSet": "$event_type"},
                    "start_time": {"$min": "$timestamp"},
                    "end_time": {"$max": "$timestamp"},
                }
            },
            {"$project": {"_id": 0}},
        ]

        doc = await anext(EventDocument.aggregate(pipeline), None)
        if not doc:
            return None
        # Only pass keys that Event dataclass accepts (filters out _id, revision_id, etc.)
        event_keys = {f.name for f in fields(Event)}
        return EventReplayInfo(
            events=[Event(**{k: v for k, v in e.items() if k in event_keys}) for e in doc["events"]],
            **{k: v for k, v in doc.items() if k != "events"},
        )
