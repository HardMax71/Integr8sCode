import dataclasses
from datetime import datetime, timedelta, timezone
from typing import Any

from beanie.odm.enums import SortDirection
from beanie.operators import GTE, LTE, In, Text
from monggregate import Pipeline, S

from app.db.docs import (
    EventArchiveDocument,
    EventDocument,
    ExecutionDocument,
    ReplaySessionDocument,
)
from app.domain.admin import ExecutionResultSummary, ReplaySessionUpdate
from app.domain.enums import EventType, ExecutionStatus
from app.domain.events import (
    DomainEvent,
    DomainEventAdapter,
    EventBrowseResult,
    EventDetail,
    EventFilter,
    EventStatistics,
    EventSummary,
    EventTypeCount,
    HourlyEventCount,
    ResourceUsageDomain,
    UserEventCount,
)
from app.domain.replay import ReplayFilter


class AdminEventsRepository:
    def _event_filter_conditions(self, f: EventFilter) -> list[Any]:
        """Build Beanie query conditions from EventFilter for EventDocument."""
        conditions = [
            In(EventDocument.event_type, f.event_types) if f.event_types else None,
            EventDocument.aggregate_id == f.aggregate_id if f.aggregate_id else None,
            EventDocument.metadata.user_id == f.user_id if f.user_id else None,
            EventDocument.metadata.service_name == f.service_name if f.service_name else None,
            GTE(EventDocument.timestamp, f.start_time) if f.start_time else None,
            LTE(EventDocument.timestamp, f.end_time) if f.end_time else None,
            Text(f.search_text) if f.search_text else None,
        ]
        return [c for c in conditions if c is not None]

    async def get_events(
        self,
        event_filter: EventFilter,
        skip: int = 0,
        limit: int = 50,
    ) -> list[DomainEvent]:
        conditions = self._event_filter_conditions(event_filter)
        docs = (
            await EventDocument.find(*conditions)
            .sort([("timestamp", SortDirection.DESCENDING)])
            .skip(skip)
            .limit(limit)
            .to_list()
        )
        return [DomainEventAdapter.validate_python(d) for d in docs]

    async def get_events_page(
        self,
        event_filter: EventFilter,
        skip: int = 0,
        limit: int = 50,
    ) -> EventBrowseResult:
        conditions = self._event_filter_conditions(event_filter)
        query = EventDocument.find(*conditions)
        total = await query.count()
        docs = await query.sort([("timestamp", SortDirection.DESCENDING)]).skip(skip).limit(limit).to_list()
        events = [DomainEventAdapter.validate_python(d) for d in docs]
        return EventBrowseResult(events=events, total=total, skip=skip, limit=limit)

    async def get_event_detail(self, event_id: str) -> EventDetail | None:
        doc = await EventDocument.find_one(EventDocument.event_id == event_id)
        if not doc:
            return None

        event = DomainEventAdapter.validate_python(doc)

        related_query = {"aggregate_id": doc.aggregate_id, "event_id": {"$ne": event_id}}
        related_docs = await (
            EventDocument.find(related_query).sort([("timestamp", SortDirection.ASCENDING)]).limit(10).to_list()
        )
        related_events = [
            EventSummary(
                event_id=d.event_id,
                event_type=d.event_type,
                timestamp=d.timestamp,
                aggregate_id=d.aggregate_id,
            )
            for d in related_docs
        ]
        timeline = related_events[:5]

        return EventDetail(event=event, related_events=related_events, timeline=timeline)

    async def delete_event(self, event_id: str) -> bool:
        doc = await EventDocument.find_one(EventDocument.event_id == event_id)
        if not doc:
            return False
        await doc.delete()
        return True

    async def get_event_stats(self, hours: int = 24) -> EventStatistics:
        start_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        event_pipeline: list[dict[str, Any]] = [
            {"$match": {"timestamp": {"$gte": start_time}}},
            {
                "$facet": {
                    "overview": [
                        {
                            "$group": {
                                "_id": None,
                                "total_events": {"$sum": 1},
                                "event_types": {"$addToSet": S.field(EventDocument.event_type)},
                                "unique_users": {"$addToSet": S.field(EventDocument.metadata.user_id)},
                                "services": {"$addToSet": S.field(EventDocument.metadata.service_name)},
                            }
                        },
                        {
                            "$project": {
                                "_id": 0,
                                "total_events": 1,
                                "event_type_count": {"$size": "$event_types"},
                                "unique_user_count": {"$size": "$unique_users"},
                                "service_count": {"$size": "$services"},
                            }
                        },
                    ],
                    "error_count": [
                        {"$match": {"event_type": {"$regex": "failed|error|timeout", "$options": "i"}}},
                        {"$count": "count"},
                    ],
                    "by_type": [
                        {"$group": {"_id": S.field(EventDocument.event_type), "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}},
                        {"$limit": 10},
                    ],
                    "by_hour": [
                        {
                            "$group": {
                                "_id": {
                                    "$dateToString": {
                                        "format": "%Y-%m-%d-%H",
                                        "date": S.field(EventDocument.timestamp),
                                    }
                                },
                                "count": {"$sum": 1},
                            }
                        },
                        {"$sort": {"_id": 1}},
                        {"$project": {"_id": 0, "hour": "$_id", "count": 1}},
                    ],
                    "by_user": [
                        {"$group": {"_id": S.field(EventDocument.metadata.user_id), "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}},
                        {"$limit": 10},
                        {"$project": {"_id": 0, "user_id": "$_id", "event_count": "$count"}},
                    ],
                }
            },
        ]
        event_results = await EventDocument.aggregate(event_pipeline).to_list()

        facet = event_results[0] if event_results else {}
        overview = (
            facet["overview"][0]
            if facet.get("overview")
            else {"total_events": 0, "event_type_count": 0, "unique_user_count": 0, "service_count": 0}
        )
        error_list = facet.get("error_count", [])
        error_count = error_list[0]["count"] if error_list else 0
        total = overview["total_events"]
        error_rate = (error_count / total * 100) if total > 0 else 0

        events_by_type = [
            EventTypeCount(event_type=EventType(t["_id"]), count=t["count"])
            for t in facet.get("by_type", [])
        ]
        events_by_hour = [HourlyEventCount(**doc) for doc in facet.get("by_hour", [])]
        top_users = [
            UserEventCount(**doc) for doc in facet.get("by_user", []) if doc["user_id"]
        ]

        # Separate collection — must be a separate query
        exec_time_field = S.field(ExecutionDocument.resource_usage.execution_time_wall_seconds)  # type: ignore[union-attr]
        exec_pipeline = (
            Pipeline()
            .match({
                ExecutionDocument.created_at: {"$gte": start_time},
                ExecutionDocument.status: ExecutionStatus.COMPLETED,
                ExecutionDocument.resource_usage.execution_time_wall_seconds: {"$exists": True},  # type: ignore[union-attr]
            })
            .group(by=None, query={"avg_duration": S.avg(exec_time_field)})
        )
        exec_result = await ExecutionDocument.aggregate(exec_pipeline.export()).to_list()
        avg_processing_time = (
            exec_result[0]["avg_duration"] if exec_result and exec_result[0].get("avg_duration") else 0
        )

        return EventStatistics(
            total_events=total,
            events_by_type=events_by_type,
            events_by_hour=events_by_hour,
            top_users=top_users,
            error_rate=round(error_rate, 2),
            avg_processing_time=round(avg_processing_time, 2),
        )

    async def archive_event(self, event: DomainEvent, deleted_by: str) -> bool:
        archive_doc = EventArchiveDocument(
            **event.model_dump(),
            deleted_at=datetime.now(timezone.utc),
            deleted_by=deleted_by,
        )
        await archive_doc.insert()
        return True

    async def update_replay_session(self, session_id: str, updates: ReplaySessionUpdate) -> bool:
        update_dict = {k: v for k, v in dataclasses.asdict(updates).items() if v is not None}
        if not update_dict:
            return False
        doc = await ReplaySessionDocument.find_one(ReplaySessionDocument.session_id == session_id)
        if not doc:
            return False
        await doc.set(update_dict)
        return True

    async def get_replay_session_doc(self, session_id: str) -> ReplaySessionDocument | None:
        return await ReplaySessionDocument.find_one(ReplaySessionDocument.session_id == session_id)

    async def get_execution_results_for_filter(
        self, replay_filter: ReplayFilter,
    ) -> list[ExecutionResultSummary]:
        mongo_query = replay_filter.to_mongo_query()
        if not mongo_query:
            return []
        matched_events = await EventDocument.find(mongo_query).limit(100).to_list()
        exec_ids = list({e.execution_id for e in matched_events if e.execution_id})[:10]
        if not exec_ids:
            return []
        exec_docs = await ExecutionDocument.find(
            In(ExecutionDocument.execution_id, exec_ids)
        ).to_list()
        return [
            ExecutionResultSummary(
                execution_id=d.execution_id,
                status=d.status,
                stdout=d.stdout,
                stderr=d.stderr,
                exit_code=d.exit_code,
                lang=d.lang,
                lang_version=d.lang_version,
                created_at=d.created_at,
                updated_at=d.updated_at,
                resource_usage=ResourceUsageDomain(**d.resource_usage.model_dump()) if d.resource_usage else None,
                error_type=d.error_type,
            )
            for d in exec_docs
        ]

    async def count_events_for_replay(self, replay_filter: ReplayFilter) -> int:
        return await EventDocument.find(replay_filter.to_mongo_query()).count()

    async def get_events_preview_for_replay(self, replay_filter: ReplayFilter, limit: int = 100) -> list[EventSummary]:
        docs = await EventDocument.find(replay_filter.to_mongo_query()).limit(limit).to_list()
        return [
            EventSummary(
                event_id=doc.event_id,
                event_type=doc.event_type,
                timestamp=doc.timestamp,
                aggregate_id=doc.aggregate_id,
            )
            for doc in docs
        ]
