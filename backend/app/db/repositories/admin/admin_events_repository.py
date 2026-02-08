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
from app.domain.admin import ExecutionResultSummary, ReplaySessionData, ReplaySessionStatusDetail
from app.domain.admin.replay_updates import ReplaySessionUpdate
from app.domain.enums import EventType, ReplayStatus
from app.domain.events import (
    DomainEvent,
    DomainEventAdapter,
    EventBrowseResult,
    EventDetail,
    EventExportRow,
    EventFilter,
    EventStatistics,
    EventSummary,
    EventTypeCount,
    HourlyEventCount,
    UserEventCount,
)
from app.domain.replay.models import ReplayFilter, ReplaySessionState


class AdminEventsRepository:
    def _event_filter_conditions(self, f: EventFilter) -> list[Any]:
        """Build Beanie query conditions from EventFilter for EventDocument."""
        conditions = [
            In(EventDocument.event_type, f.event_types) if f.event_types else None,
            EventDocument.aggregate_id == f.aggregate_id if f.aggregate_id else None,
            EventDocument.metadata.correlation_id == f.correlation_id if f.correlation_id else None,
            EventDocument.metadata.user_id == f.user_id if f.user_id else None,
            EventDocument.metadata.service_name == f.service_name if f.service_name else None,
            GTE(EventDocument.timestamp, f.start_time) if f.start_time else None,
            LTE(EventDocument.timestamp, f.end_time) if f.end_time else None,
            Text(f.search_text) if f.search_text else None,
        ]
        return [c for c in conditions if c is not None]

    async def browse_events(
        self,
        event_filter: EventFilter,
        skip: int = 0,
        limit: int = 50,
        sort_by: str = "timestamp",
        sort_order: SortDirection = SortDirection.DESCENDING,
    ) -> EventBrowseResult:
        conditions = self._event_filter_conditions(event_filter)
        query = EventDocument.find(*conditions)
        total = await query.count()

        docs = await query.sort([(sort_by, sort_order)]).skip(skip).limit(limit).to_list()
        events = [DomainEventAdapter.validate_python(d, from_attributes=True) for d in docs]

        return EventBrowseResult(events=events, total=total, skip=skip, limit=limit)

    async def get_event_detail(self, event_id: str) -> EventDetail | None:
        doc = await EventDocument.find_one(EventDocument.event_id == event_id)
        if not doc:
            return None

        event = DomainEventAdapter.validate_python(doc, from_attributes=True)

        related_query = {"metadata.correlation_id": doc.metadata.correlation_id, "event_id": {"$ne": event_id}}
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

        # Overview stats pipeline
        # Note: monggregate doesn't have S.add_to_set - use raw dict syntax
        overview_pipeline = (
            Pipeline()
            .match({EventDocument.timestamp: {"$gte": start_time}})
            .group(
                by=None,
                query={
                    "total_events": S.sum(1),
                    "event_types": {"$addToSet": S.field(EventDocument.event_type)},
                    "unique_users": {"$addToSet": S.field(EventDocument.metadata.user_id)},
                    "services": {"$addToSet": S.field(EventDocument.metadata.service_name)},
                },
            )
            .project(
                _id=0,
                total_events=1,
                event_type_count={"$size": "$event_types"},
                unique_user_count={"$size": "$unique_users"},
                service_count={"$size": "$services"},
            )
        )
        overview_result = await EventDocument.aggregate(overview_pipeline.export()).to_list()
        stats = (
            overview_result[0]
            if overview_result
            else {"total_events": 0, "event_type_count": 0, "unique_user_count": 0, "service_count": 0}
        )

        error_count = await EventDocument.find(
            {
                EventDocument.timestamp: {"$gte": start_time},
                EventDocument.event_type: {"$regex": "failed|error|timeout", "$options": "i"},
            }
        ).count()
        error_rate = (error_count / stats["total_events"] * 100) if stats["total_events"] > 0 else 0

        # Event types pipeline
        type_pipeline = (
            Pipeline()
            .match({EventDocument.timestamp: {"$gte": start_time}})
            .group(by=S.field(EventDocument.event_type), query={"count": S.sum(1)})
            .sort(by="count", descending=True)
            .limit(10)
        )
        top_types = await EventDocument.aggregate(type_pipeline.export()).to_list()
        events_by_type = [EventTypeCount(event_type=EventType(t["_id"]), count=t["count"]) for t in top_types]

        # Hourly events pipeline - project renames _id->hour
        hourly_pipeline = (
            Pipeline()
            .match({EventDocument.timestamp: {"$gte": start_time}})
            .group(
                by={"$dateToString": {"format": "%Y-%m-%d-%H", "date": S.field(EventDocument.timestamp)}},
                query={"count": S.sum(1)},
            )
            .sort(by="_id")
            .project(_id=0, hour="$_id", count=1)
        )
        hourly_result = await EventDocument.aggregate(hourly_pipeline.export()).to_list()
        events_by_hour: list[HourlyEventCount | dict[str, Any]] = [HourlyEventCount(**doc) for doc in hourly_result]

        # Top users pipeline - project renames _id->user_id, count->event_count
        user_pipeline = (
            Pipeline()
            .match({EventDocument.timestamp: {"$gte": start_time}})
            .group(by=S.field(EventDocument.metadata.user_id), query={"count": S.sum(1)})
            .sort(by="count", descending=True)
            .limit(10)
            .project(_id=0, user_id="$_id", event_count="$count")
        )
        top_users_result = await EventDocument.aggregate(user_pipeline.export()).to_list()
        top_users = [UserEventCount(**doc) for doc in top_users_result if doc["user_id"]]

        # Execution duration pipeline
        exec_time_field = S.field(ExecutionDocument.resource_usage.execution_time_wall_seconds)  # type: ignore[union-attr]
        exec_pipeline = (
            Pipeline()
            .match({
                ExecutionDocument.created_at: {"$gte": start_time},
                ExecutionDocument.status: "completed",
                ExecutionDocument.resource_usage.execution_time_wall_seconds: {"$exists": True},  # type: ignore[union-attr]
            })
            .group(by=None, query={"avg_duration": S.avg(exec_time_field)})
        )
        exec_result = await ExecutionDocument.aggregate(exec_pipeline.export()).to_list()
        avg_processing_time = (
            exec_result[0]["avg_duration"] if exec_result and exec_result[0].get("avg_duration") else 0
        )

        return EventStatistics(
            total_events=stats["total_events"],
            events_by_type=events_by_type,
            events_by_hour=events_by_hour,
            top_users=top_users,
            error_rate=round(error_rate, 2),
            avg_processing_time=round(avg_processing_time, 2),
        )

    async def export_events_csv(self, event_filter: EventFilter) -> list[EventExportRow]:
        conditions = self._event_filter_conditions(event_filter)
        docs = await (
            EventDocument.find(*conditions).sort([("timestamp", SortDirection.DESCENDING)]).limit(10000).to_list()
        )

        return [
            EventExportRow(
                event_id=doc.event_id,
                event_type=doc.event_type,
                timestamp=doc.timestamp,
                correlation_id=doc.metadata.correlation_id or "",
                aggregate_id=doc.aggregate_id or "",
                user_id=doc.metadata.user_id or "",
                service=doc.metadata.service_name,
                status="",
                error="",
            )
            for doc in docs
        ]

    async def archive_event(self, event: DomainEvent, deleted_by: str) -> bool:
        archive_doc = EventArchiveDocument(
            **event.model_dump(),
            deleted_at=datetime.now(timezone.utc),
            deleted_by=deleted_by,
        )
        await archive_doc.insert()
        return True

    async def create_replay_session(self, session: ReplaySessionState) -> str:
        doc = ReplaySessionDocument(**session.model_dump())
        await doc.insert()
        return session.session_id

    async def get_replay_session(self, session_id: str) -> ReplaySessionState | None:
        doc = await ReplaySessionDocument.find_one(ReplaySessionDocument.session_id == session_id)
        if not doc:
            return None
        return ReplaySessionState.model_validate(doc, from_attributes=True)

    async def update_replay_session(self, session_id: str, updates: ReplaySessionUpdate) -> bool:
        update_dict = updates.model_dump(exclude_none=True)
        if not update_dict:
            return False
        doc = await ReplaySessionDocument.find_one(ReplaySessionDocument.session_id == session_id)
        if not doc:
            return False
        await doc.set(update_dict)
        return True

    async def get_replay_status_with_progress(self, session_id: str) -> ReplaySessionStatusDetail | None:
        doc = await ReplaySessionDocument.find_one(ReplaySessionDocument.session_id == session_id)
        if not doc:
            return None

        current_time = datetime.now(timezone.utc)

        # Auto-transition from SCHEDULED to RUNNING after 2 seconds
        if doc.status == ReplayStatus.SCHEDULED and doc.created_at:
            time_since_created = current_time - doc.created_at
            if time_since_created.total_seconds() > 2:
                doc.status = ReplayStatus.RUNNING
                doc.started_at = current_time
                await doc.save()

        # Update progress for running sessions
        if doc.is_running and doc.started_at:
            time_since_started = current_time - doc.started_at
            estimated_progress = min(int(time_since_started.total_seconds() * 10), doc.total_events)
            doc.replayed_events = estimated_progress

            # Check if completed
            if doc.replayed_events >= doc.total_events:
                doc.status = ReplayStatus.COMPLETED
                doc.completed_at = current_time
            await doc.save()

        # Calculate estimated completion time
        estimated_completion = None
        if doc.is_running and doc.replayed_events > 0 and doc.started_at:
            elapsed = (current_time - doc.started_at).total_seconds()
            if elapsed > 0:
                rate = doc.replayed_events / elapsed
                remaining = doc.total_events - doc.replayed_events
                if rate > 0:
                    estimated_completion = current_time + timedelta(seconds=remaining / rate)

        # Fetch related execution results
        execution_results: list[ExecutionResultSummary] = []
        if doc.config and doc.config.filter and doc.config.filter.custom_query:
            original_query = doc.config.filter.custom_query
            original_events = await EventDocument.find(original_query).limit(10).to_list()

            execution_ids = {event.execution_id for event in original_events if event.execution_id}

            for exec_id in list(execution_ids)[:10]:
                exec_doc = await ExecutionDocument.find_one(ExecutionDocument.execution_id == exec_id)
                if exec_doc:
                    execution_results.append(
                        ExecutionResultSummary(
                            execution_id=exec_doc.execution_id,
                            status=exec_doc.status if exec_doc.status else None,
                            stdout=exec_doc.stdout,
                            stderr=exec_doc.stderr,
                            exit_code=exec_doc.exit_code,
                            lang=exec_doc.lang,
                            lang_version=exec_doc.lang_version,
                            created_at=exec_doc.created_at,
                            updated_at=exec_doc.updated_at,
                        )
                    )

        # Convert document to domain
        session = ReplaySessionState.model_validate(doc, from_attributes=True)

        return ReplaySessionStatusDetail(
            session=session,
            estimated_completion=estimated_completion,
            execution_results=execution_results,
        )

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

    async def prepare_replay_session(
        self, replay_filter: ReplayFilter, dry_run: bool, replay_correlation_id: str, max_events: int = 1000
    ) -> ReplaySessionData:
        event_count = await self.count_events_for_replay(replay_filter)
        if event_count == 0:
            raise ValueError("No events found matching the criteria")
        if event_count > max_events and not dry_run:
            raise ValueError(f"Too many events to replay ({event_count}). Maximum is {max_events}.")

        events_preview: list[EventSummary] = []
        if dry_run:
            events_preview = await self.get_events_preview_for_replay(replay_filter, limit=100)

        return ReplaySessionData(
            total_events=event_count,
            replay_correlation_id=replay_correlation_id,
            dry_run=dry_run,
            filter=replay_filter,
            events_preview=events_preview,
        )

    async def get_replay_events_preview(
        self, event_ids: list[str] | None = None, correlation_id: str | None = None, aggregate_id: str | None = None
    ) -> dict[str, Any]:
        replay_filter = ReplayFilter(event_ids=event_ids, correlation_id=correlation_id, aggregate_id=aggregate_id)
        query = replay_filter.to_mongo_query()

        if not query:
            return {"events": [], "total": 0}

        total = await EventDocument.find(query).count()
        docs = await EventDocument.find(query).sort([("timestamp", SortDirection.ASCENDING)]).limit(100).to_list()

        events = [doc.model_dump() for doc in docs]
        return {"events": events, "total": total}
