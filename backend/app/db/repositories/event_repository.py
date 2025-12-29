import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from beanie.operators import GTE, LT, LTE, GT, In, Not, Or, RegEx

from pymongo import ASCENDING, DESCENDING

from app.core.tracing import EventAttributes
from app.core.tracing.utils import add_span_attributes
from app.db.docs import EventDocument, EventArchiveDocument
from app.domain.enums.events import EventType


class EventListResult:
    def __init__(self, events: list[EventDocument], total: int, skip: int, limit: int, has_more: bool = False):
        self.events = events
        self.total = total
        self.skip = skip
        self.limit = limit
        self.has_more = has_more


class EventStatistics:
    def __init__(self, total_events: int, events_by_type: dict, events_by_service: dict, events_by_hour: list):
        self.total_events = total_events
        self.events_by_type = events_by_type
        self.events_by_service = events_by_service
        self.events_by_hour = events_by_hour


class EventAggregationResult:
    def __init__(self, results: list, pipeline: list):
        self.results = results
        self.pipeline = pipeline


class EventReplayInfo:
    def __init__(self, events: list, event_count: int, event_types: list, start_time: datetime, end_time: datetime):
        self.events = events
        self.event_count = event_count
        self.event_types = event_types
        self.start_time = start_time
        self.end_time = end_time


class EventRepository:

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    def _time_conditions(self, start_time: datetime | None, end_time: datetime | None) -> list:
        """Build time range conditions for queries."""
        conditions = [
            GTE(EventDocument.timestamp, start_time) if start_time else None,
            LTE(EventDocument.timestamp, end_time) if end_time else None,
        ]
        return [c for c in conditions if c is not None]

    def _build_time_filter(self, start_time: datetime | None, end_time: datetime | None) -> dict[str, object]:
        """Build time filter dict for aggregation pipelines."""
        return {key: value for key, value in {"$gte": start_time, "$lte": end_time}.items() if value is not None}

    async def store_event(self, event: EventDocument) -> str:
        if not event.stored_at:
            event.stored_at = datetime.now(timezone.utc)

        add_span_attributes(
            **{
                str(EventAttributes.EVENT_TYPE): str(event.event_type),
                str(EventAttributes.EVENT_ID): event.event_id,
                str(EventAttributes.EXECUTION_ID): event.aggregate_id or "",
            }
        )
        await event.insert()
        self.logger.debug(f"Stored event {event.event_id} of type {event.event_type}")
        return event.event_id

    async def store_events_batch(self, events: list[EventDocument]) -> list[str]:
        if not events:
            return []
        now = datetime.now(timezone.utc)
        for event in events:
            if not event.stored_at:
                event.stored_at = now
        await EventDocument.insert_many(events)
        add_span_attributes(**{"events.batch.count": len(events)})
        self.logger.info(f"Stored {len(events)} events in batch")
        return [event.event_id for event in events]

    async def get_event(self, event_id: str) -> EventDocument | None:
        return await EventDocument.find_one({"event_id": event_id})

    async def get_events_by_type(
        self,
        event_type: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        skip: int = 0,
    ) -> list[EventDocument]:
        conditions = [
            EventDocument.event_type == event_type,
            *self._time_conditions(start_time, end_time),
        ]
        return await EventDocument.find(*conditions).sort([("timestamp", DESCENDING)]).skip(skip).limit(limit).to_list()

    async def get_events_by_aggregate(
        self, aggregate_id: str, event_types: list[EventType] | None = None, limit: int = 100
    ) -> list[EventDocument]:
        conditions = [
            EventDocument.aggregate_id == aggregate_id,
            In(EventDocument.event_type, [t.value for t in event_types]) if event_types else None,
        ]
        conditions = [c for c in conditions if c is not None]
        return await EventDocument.find(*conditions).sort([("timestamp", ASCENDING)]).limit(limit).to_list()

    async def get_events_by_correlation(self, correlation_id: str, limit: int = 100, skip: int = 0) -> EventListResult:
        query = EventDocument.find(EventDocument.metadata.correlation_id == correlation_id)
        total_count = await query.count()
        events = await query.sort([("timestamp", ASCENDING)]).skip(skip).limit(limit).to_list()
        return EventListResult(
            events=events,
            total=total_count,
            skip=skip,
            limit=limit,
            has_more=(skip + limit) < total_count,
        )

    async def get_events_by_user(
        self,
        user_id: str,
        event_types: list[str] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        skip: int = 0,
    ) -> list[EventDocument]:
        conditions = [
            EventDocument.metadata.user_id == user_id,
            In(EventDocument.event_type, event_types) if event_types else None,
            *self._time_conditions(start_time, end_time),
        ]
        conditions = [c for c in conditions if c is not None]
        return await EventDocument.find(*conditions).sort([("timestamp", DESCENDING)]).skip(skip).limit(limit).to_list()

    async def get_execution_events(
        self, execution_id: str, limit: int = 100, skip: int = 0, exclude_system_events: bool = False
    ) -> EventListResult:
        conditions = [
            Or(
                EventDocument.payload["execution_id"] == execution_id,
                EventDocument.aggregate_id == execution_id,
            ),
            Not(RegEx(EventDocument.metadata.service_name, "^system-")) if exclude_system_events else None,
        ]
        conditions = [c for c in conditions if c is not None]
        query = EventDocument.find(*conditions)
        total_count = await query.count()
        events = await query.sort([("timestamp", ASCENDING)]).skip(skip).limit(limit).to_list()
        return EventListResult(
            events=events,
            total=total_count,
            skip=skip,
            limit=limit,
            has_more=(skip + limit) < total_count,
        )

    async def get_event_statistics(
        self, start_time: datetime | None = None, end_time: datetime | None = None
    ) -> EventStatistics:
        pipeline: list[Mapping[str, object]] = []
        time_filter = self._build_time_filter(start_time, end_time)
        if time_filter:
            pipeline.append({"$match": {"timestamp": time_filter}})

        pipeline.extend([
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
                    "events_by_hour": "$by_hour",
                }
            },
        ])

        async for doc in EventDocument.aggregate(pipeline):
            return EventStatistics(**doc)

        return EventStatistics(total_events=0, events_by_type={}, events_by_service={}, events_by_hour=[])

    async def cleanup_old_events(
        self, older_than_days: int = 30, event_types: list[str] | None = None, dry_run: bool = False
    ) -> int:
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        conditions = [
            LT(EventDocument.timestamp, cutoff_dt),
            In(EventDocument.event_type, event_types) if event_types else None,
        ]
        conditions = [c for c in conditions if c is not None]

        if dry_run:
            count = await EventDocument.find(*conditions).count()
            self.logger.info(f"Would delete {count} events older than {older_than_days} days")
            return count

        result = await EventDocument.find(*conditions).delete()
        self.logger.info(f"Deleted {result.deleted_count} events older than {older_than_days} days")
        return result.deleted_count

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
        sort_direction = DESCENDING if sort_order == "desc" else ASCENDING
        events = await query.sort([("timestamp", sort_direction)]).skip(skip).limit(limit).to_list()

        return EventListResult(
            events=events,
            total=total_count,
            skip=skip,
            limit=limit,
            has_more=(skip + limit) < total_count,
        )

    async def count_events(self, *conditions: Any) -> int:
        return await EventDocument.find(*conditions).count()

    async def delete_event_with_archival(
        self, event_id: str, deleted_by: str, deletion_reason: str = "Admin deletion via API"
    ) -> EventArchiveDocument | None:
        event = await self.get_event(event_id)
        if not event:
            return None

        archived = EventArchiveDocument(
            event_id=event.event_id,
            event_type=event.event_type,
            event_version=event.event_version,
            timestamp=event.timestamp,
            metadata=event.metadata,
            payload=event.payload,
            aggregate_id=event.aggregate_id,
            stored_at=event.stored_at,
            ttl_expires_at=event.ttl_expires_at,
            deleted_at=datetime.now(timezone.utc),
            deleted_by=deleted_by,
            deletion_reason=deletion_reason,
        )
        await archived.insert()
        await event.delete()
        return archived

    async def get_aggregate_events_for_replay(self, aggregate_id: str, limit: int = 10000) -> list[EventDocument]:
        return await self.get_events_by_aggregate(aggregate_id=aggregate_id, limit=limit)

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

        async for doc in EventDocument.aggregate(pipeline):
            return EventReplayInfo(**doc)

        return None
