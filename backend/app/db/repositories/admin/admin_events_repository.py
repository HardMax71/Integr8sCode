from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from beanie.odm.enums import SortDirection
from beanie.operators import GTE, LTE, In, Text

from app.db.docs import (
    EventArchiveDocument,
    EventStoreDocument,
    ExecutionDocument,
    ReplaySessionDocument,
)
from app.domain.admin import ReplayQuery, ReplaySessionData, ReplaySessionStatusDetail
from app.domain.admin.replay_updates import ReplaySessionUpdate
from app.domain.enums.replay import ReplayStatus
from app.domain.events import EventMetadata as DomainEventMetadata
from app.domain.events.event_models import (
    Event,
    EventBrowseResult,
    EventDetail,
    EventExportRow,
    EventFilter,
    EventStatistics,
    EventSummary,
    HourlyEventCount,
    UserEventCount,
)
from app.domain.events.query_builders import EventStatsAggregation
from app.domain.replay.models import ReplayConfig, ReplaySessionState


class AdminEventsRepository:
    def _event_filter_conditions(self, f: EventFilter) -> list[Any]:
        """Build Beanie query conditions from EventFilter for EventStoreDocument."""
        conditions = [
            In(EventStoreDocument.event_type, f.event_types) if f.event_types else None,
            EventStoreDocument.aggregate_id == f.aggregate_id if f.aggregate_id else None,
            EventStoreDocument.metadata.correlation_id == f.correlation_id if f.correlation_id else None,
            EventStoreDocument.metadata.user_id == f.user_id if f.user_id else None,
            EventStoreDocument.metadata.service_name == f.service_name if f.service_name else None,
            GTE(EventStoreDocument.timestamp, f.start_time) if f.start_time else None,
            LTE(EventStoreDocument.timestamp, f.end_time) if f.end_time else None,
            Text(f.search_text) if f.search_text else None,
        ]
        return [c for c in conditions if c is not None]

    def _replay_conditions_for_store(self, q: ReplayQuery) -> list[Any]:
        """Build Beanie query conditions from ReplayQuery for EventStoreDocument."""
        conditions = [
            In(EventStoreDocument.event_id, q.event_ids) if q.event_ids else None,
            EventStoreDocument.metadata.correlation_id == q.correlation_id if q.correlation_id else None,
            EventStoreDocument.aggregate_id == q.aggregate_id if q.aggregate_id else None,
            GTE(EventStoreDocument.timestamp, q.start_time) if q.start_time else None,
            LTE(EventStoreDocument.timestamp, q.end_time) if q.end_time else None,
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
        query = EventStoreDocument.find(*conditions)
        total = await query.count()

        docs = await query.sort([(sort_by, sort_order)]).skip(skip).limit(limit).to_list()
        doc_fields = set(EventStoreDocument.model_fields.keys()) - {"id", "revision_id"}
        events = [
            Event(**{**d.model_dump(include=doc_fields), "metadata": DomainEventMetadata(**d.metadata.model_dump())})
            for d in docs
        ]

        return EventBrowseResult(events=events, total=total, skip=skip, limit=limit)

    async def get_event_detail(self, event_id: str) -> EventDetail | None:
        doc = await EventStoreDocument.find_one({"event_id": event_id})
        if not doc:
            return None

        doc_fields = set(EventStoreDocument.model_fields.keys()) - {"id", "revision_id"}
        event = Event(
            **{**doc.model_dump(include=doc_fields), "metadata": DomainEventMetadata(**doc.metadata.model_dump())}
        )

        related_query = {"metadata.correlation_id": doc.metadata.correlation_id, "event_id": {"$ne": event_id}}
        related_docs = await (
            EventStoreDocument.find(related_query).sort([("timestamp", SortDirection.ASCENDING)]).limit(10).to_list()
        )
        related_events = [
            EventSummary(
                event_id=d.event_id,
                event_type=str(d.event_type),
                timestamp=d.timestamp,
                aggregate_id=d.aggregate_id,
            )
            for d in related_docs
        ]
        timeline = related_events[:5]

        return EventDetail(event=event, related_events=related_events, timeline=timeline)

    async def delete_event(self, event_id: str) -> bool:
        doc = await EventStoreDocument.find_one({"event_id": event_id})
        if not doc:
            return False
        await doc.delete()
        return True

    async def get_event_stats(self, hours: int = 24) -> EventStatistics:
        start_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        overview_pipeline = EventStatsAggregation.build_overview_pipeline(start_time)
        overview_result = await EventStoreDocument.aggregate(overview_pipeline).to_list()

        stats = (
            overview_result[0]
            if overview_result
            else {"total_events": 0, "event_type_count": 0, "unique_user_count": 0, "service_count": 0}
        )

        error_count = await EventStoreDocument.find(
            {
                "timestamp": {"$gte": start_time},
                "event_type": {"$regex": "failed|error|timeout", "$options": "i"},
            }
        ).count()

        error_rate = (error_count / stats["total_events"] * 100) if stats["total_events"] > 0 else 0

        type_pipeline = EventStatsAggregation.build_event_types_pipeline(start_time)
        top_types = await EventStoreDocument.aggregate(type_pipeline).to_list()
        events_by_type = {t["_id"]: t["count"] for t in top_types}

        hourly_pipeline = EventStatsAggregation.build_hourly_events_pipeline(start_time)
        hourly_result = await EventStoreDocument.aggregate(hourly_pipeline).to_list()
        events_by_hour: list[HourlyEventCount | dict[str, Any]] = [
            HourlyEventCount(hour=doc["_id"], count=doc["count"]) for doc in hourly_result
        ]

        user_pipeline = EventStatsAggregation.build_top_users_pipeline(start_time)
        top_users_result = await EventStoreDocument.aggregate(user_pipeline).to_list()
        top_users = [
            UserEventCount(user_id=doc["_id"], event_count=doc["count"]) for doc in top_users_result if doc["_id"]
        ]

        exec_pipeline: list[dict[str, Any]] = [
            {
                "$match": {
                    "created_at": {"$gte": start_time},
                    "status": "completed",
                    "resource_usage.execution_time_wall_seconds": {"$exists": True},
                }
            },
            {"$group": {"_id": None, "avg_duration": {"$avg": "$resource_usage.execution_time_wall_seconds"}}},
        ]

        exec_result = await ExecutionDocument.aggregate(exec_pipeline).to_list()
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
            EventStoreDocument.find(*conditions).sort([("timestamp", SortDirection.DESCENDING)]).limit(10000).to_list()
        )

        return [
            EventExportRow(
                event_id=doc.event_id,
                event_type=str(doc.event_type),
                timestamp=doc.timestamp.isoformat(),
                correlation_id=doc.metadata.correlation_id or "",
                aggregate_id=doc.aggregate_id or "",
                user_id=doc.metadata.user_id or "",
                service=doc.metadata.service_name,
                status="",
                error="",
            )
            for doc in docs
        ]

    async def archive_event(self, event: Event, deleted_by: str) -> bool:
        archive_doc = EventArchiveDocument(
            event_id=event.event_id,
            event_type=event.event_type,
            event_version=event.event_version,
            timestamp=event.timestamp,
            aggregate_id=event.aggregate_id,
            metadata=event.metadata,
            payload=event.payload,
            stored_at=event.stored_at,
            ttl_expires_at=event.ttl_expires_at,
            deleted_at=datetime.now(timezone.utc),
            deleted_by=deleted_by,
        )
        await archive_doc.insert()
        return True

    async def create_replay_session(self, session: ReplaySessionState) -> str:
        data = asdict(session)
        data["config"] = session.config.model_dump()
        doc = ReplaySessionDocument(**data)
        await doc.insert()
        return session.session_id

    async def get_replay_session(self, session_id: str) -> ReplaySessionState | None:
        doc = await ReplaySessionDocument.find_one({"session_id": session_id})
        if not doc:
            return None
        data = doc.model_dump(exclude={"id", "revision_id"})
        data["config"] = ReplayConfig.model_validate(data["config"])
        return ReplaySessionState(**data)

    async def update_replay_session(self, session_id: str, updates: ReplaySessionUpdate) -> bool:
        update_dict = {k: (v.value if hasattr(v, "value") else v) for k, v in asdict(updates).items() if v is not None}
        if not update_dict:
            return False

        doc = await ReplaySessionDocument.find_one({"session_id": session_id})
        if not doc:
            return False

        await doc.set(update_dict)
        return True

    async def get_replay_status_with_progress(self, session_id: str) -> ReplaySessionStatusDetail | None:
        doc = await ReplaySessionDocument.find_one({"session_id": session_id})
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
        execution_results: list[dict[str, Any]] = []
        if doc.config and doc.config.filter and doc.config.filter.custom_query:
            original_query = doc.config.filter.custom_query
            original_events = await EventStoreDocument.find(original_query).limit(10).to_list()

            execution_ids = set()
            for event in original_events:
                exec_id = event.payload.get("execution_id") or event.aggregate_id
                if exec_id:
                    execution_ids.add(exec_id)

            for exec_id in list(execution_ids)[:10]:
                exec_doc = await ExecutionDocument.find_one({"execution_id": exec_id})
                if exec_doc:
                    execution_results.append(
                        {
                            "execution_id": exec_doc.execution_id,
                            "status": exec_doc.status.value if exec_doc.status else None,
                            "stdout": exec_doc.stdout,
                            "stderr": exec_doc.stderr,
                            "exit_code": exec_doc.exit_code,
                            "lang": exec_doc.lang,
                            "lang_version": exec_doc.lang_version,
                            "created_at": exec_doc.created_at,
                            "updated_at": exec_doc.updated_at,
                        }
                    )

        # Convert document to domain
        data = doc.model_dump(exclude={"id", "revision_id"})
        data["config"] = ReplayConfig.model_validate(data["config"])
        session = ReplaySessionState(**data)

        return ReplaySessionStatusDetail(
            session=session,
            estimated_completion=estimated_completion,
            execution_results=execution_results,
        )

    async def count_events_for_replay(self, replay_query: ReplayQuery) -> int:
        conditions = self._replay_conditions_for_store(replay_query)
        return await EventStoreDocument.find(*conditions).count()

    async def get_events_preview_for_replay(self, replay_query: ReplayQuery, limit: int = 100) -> list[EventSummary]:
        conditions = self._replay_conditions_for_store(replay_query)
        docs = await EventStoreDocument.find(*conditions).limit(limit).to_list()
        return [
            EventSummary(
                event_id=doc.event_id,
                event_type=str(doc.event_type),
                timestamp=doc.timestamp,
                aggregate_id=doc.aggregate_id,
            )
            for doc in docs
        ]

    async def prepare_replay_session(
        self, replay_query: ReplayQuery, dry_run: bool, replay_correlation_id: str, max_events: int = 1000
    ) -> ReplaySessionData:
        event_count = await self.count_events_for_replay(replay_query)
        if event_count == 0:
            raise ValueError("No events found matching the criteria")
        if event_count > max_events and not dry_run:
            raise ValueError(f"Too many events to replay ({event_count}). Maximum is {max_events}.")

        events_preview: list[EventSummary] = []
        if dry_run:
            events_preview = await self.get_events_preview_for_replay(replay_query, limit=100)

        return ReplaySessionData(
            total_events=event_count,
            replay_correlation_id=replay_correlation_id,
            dry_run=dry_run,
            query=replay_query,
            events_preview=events_preview,
        )

    async def get_replay_events_preview(
        self, event_ids: list[str] | None = None, correlation_id: str | None = None, aggregate_id: str | None = None
    ) -> dict[str, Any]:
        replay_query = ReplayQuery(event_ids=event_ids, correlation_id=correlation_id, aggregate_id=aggregate_id)
        conditions = self._replay_conditions_for_store(replay_query)

        if not conditions:
            return {"events": [], "total": 0}

        total = await EventStoreDocument.find(*conditions).count()
        docs = (
            await EventStoreDocument.find(*conditions)
            .sort([("timestamp", SortDirection.ASCENDING)])
            .limit(100)
            .to_list()
        )

        events = [doc.model_dump() for doc in docs]
        return {"events": events, "total": total}
