from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from pymongo import ReturnDocument

from app.core.database_context import Collection, Database
from app.domain.admin import (
    ReplayQuery,
    ReplaySession,
    ReplaySessionData,
    ReplaySessionFields,
    ReplaySessionStatusDetail,
)
from app.domain.admin.replay_updates import ReplaySessionUpdate
from app.domain.enums.replay import ReplayStatus
from app.domain.events.event_models import (
    CollectionNames,
    Event,
    EventBrowseResult,
    EventDetail,
    EventExportRow,
    EventFields,
    EventFilter,
    EventStatistics,
    EventSummary,
    HourlyEventCount,
    SortDirection,
    UserEventCount,
)
from app.domain.events.query_builders import (
    EventStatsAggregation,
)
from app.infrastructure.mappers import (
    EventExportRowMapper,
    EventFilterMapper,
    EventMapper,
    EventSummaryMapper,
    ReplayQueryMapper,
    ReplaySessionMapper,
)


class AdminEventsRepository:
    """Repository for admin event operations using domain models."""

    def __init__(self, db: Database):
        self.db = db
        self.events_collection: Collection = self.db.get_collection(CollectionNames.EVENTS)
        self.event_store_collection: Collection = self.db.get_collection(CollectionNames.EVENT_STORE)
        # Bind related collections used by this repository
        self.executions_collection: Collection = self.db.get_collection(CollectionNames.EXECUTIONS)
        self.events_archive_collection: Collection = self.db.get_collection(CollectionNames.EVENTS_ARCHIVE)
        self.replay_mapper = ReplaySessionMapper()
        self.replay_query_mapper = ReplayQueryMapper()
        self.replay_sessions_collection: Collection = self.db.get_collection(CollectionNames.REPLAY_SESSIONS)
        self.mapper = EventMapper()
        self.summary_mapper = EventSummaryMapper()

    async def browse_events(
        self,
        filter: EventFilter,
        skip: int = 0,
        limit: int = 50,
        sort_by: str = EventFields.TIMESTAMP,
        sort_order: int = SortDirection.DESCENDING,
    ) -> EventBrowseResult:
        """Browse events with filters using domain models."""
        query = EventFilterMapper.to_mongo_query(filter)

        # Get total count
        total = await self.events_collection.count_documents(query)

        # Execute query with pagination
        cursor = self.events_collection.find(query)
        cursor = cursor.sort(sort_by, sort_order)
        cursor = cursor.skip(skip).limit(limit)

        # Fetch events and convert to domain models
        event_docs = await cursor.to_list(length=limit)
        events = [self.mapper.from_mongo_document(doc) for doc in event_docs]

        return EventBrowseResult(events=events, total=total, skip=skip, limit=limit)

    async def get_event_detail(self, event_id: str) -> EventDetail | None:
        """Get detailed information about an event."""
        event_doc = await self.events_collection.find_one({EventFields.EVENT_ID: event_id})

        if not event_doc:
            return None

        event = self.mapper.from_mongo_document(event_doc)

        # Get related events
        cursor = (
            self.events_collection.find(
                {EventFields.METADATA_CORRELATION_ID: event.correlation_id, EventFields.EVENT_ID: {"$ne": event_id}}
            )
            .sort(EventFields.TIMESTAMP, SortDirection.ASCENDING)
            .limit(10)
        )

        related_docs = await cursor.to_list(length=10)
        related_events = [self.summary_mapper.from_mongo_document(doc) for doc in related_docs]

        # Build timeline (could be expanded with more logic)
        timeline = related_events[:5]  # Simple timeline for now

        detail = EventDetail(event=event, related_events=related_events, timeline=timeline)

        return detail

    async def delete_event(self, event_id: str) -> bool:
        """Delete an event."""
        result = await self.events_collection.delete_one({EventFields.EVENT_ID: event_id})
        return result.deleted_count > 0

    async def get_event_stats(self, hours: int = 24) -> EventStatistics:
        """Get event statistics for the last N hours."""
        start_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Get overview statistics
        overview_pipeline = EventStatsAggregation.build_overview_pipeline(start_time)
        overview_result = await self.events_collection.aggregate(overview_pipeline).to_list(1)

        stats = (
            overview_result[0]
            if overview_result
            else {"total_events": 0, "event_type_count": 0, "unique_user_count": 0, "service_count": 0}
        )

        # Get error rate
        error_count = await self.events_collection.count_documents(
            {
                EventFields.TIMESTAMP: {"$gte": start_time},
                EventFields.EVENT_TYPE: {"$regex": "failed|error|timeout", "$options": "i"},
            }
        )

        error_rate = (error_count / stats["total_events"] * 100) if stats["total_events"] > 0 else 0

        # Get event types with counts
        type_pipeline = EventStatsAggregation.build_event_types_pipeline(start_time)
        top_types = await self.events_collection.aggregate(type_pipeline).to_list(10)
        events_by_type = {t["_id"]: t["count"] for t in top_types}

        # Get events by hour
        hourly_pipeline = EventStatsAggregation.build_hourly_events_pipeline(start_time)
        hourly_cursor = self.events_collection.aggregate(hourly_pipeline)
        events_by_hour: list[HourlyEventCount | dict[str, Any]] = [
            HourlyEventCount(hour=doc["_id"], count=doc["count"]) async for doc in hourly_cursor
        ]

        # Get top users
        user_pipeline = EventStatsAggregation.build_top_users_pipeline(start_time)
        top_users_cursor = self.events_collection.aggregate(user_pipeline)
        top_users = [
            UserEventCount(user_id=doc["_id"], event_count=doc["count"])
            async for doc in top_users_cursor
            if doc["_id"]  # Filter out None user_ids
        ]

        # Get average processing time from executions collection
        # Since execution timing data is stored in executions, not events
        executions_collection = self.executions_collection

        # Calculate average execution time from completed executions in the last 24 hours
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

        exec_result = await executions_collection.aggregate(exec_pipeline).to_list(1)
        avg_processing_time = (
            exec_result[0]["avg_duration"] if exec_result and exec_result[0].get("avg_duration") else 0
        )

        statistics = EventStatistics(
            total_events=stats["total_events"],
            events_by_type=events_by_type,
            events_by_hour=events_by_hour,
            top_users=top_users,
            error_rate=round(error_rate, 2),
            avg_processing_time=round(avg_processing_time, 2),
        )

        return statistics

    async def export_events_csv(self, filter: EventFilter) -> List[EventExportRow]:
        """Export events as CSV data."""
        query = EventFilterMapper.to_mongo_query(filter)

        cursor = self.events_collection.find(query).sort(EventFields.TIMESTAMP, SortDirection.DESCENDING).limit(10000)

        event_docs = await cursor.to_list(length=10000)

        # Convert to export rows
        export_rows = []
        for doc in event_docs:
            event = self.mapper.from_mongo_document(doc)
            export_row = EventExportRowMapper.from_event(event)
            export_rows.append(export_row)

        return export_rows

    async def archive_event(self, event: Event, deleted_by: str) -> bool:
        """Archive an event before deletion."""
        # Add deletion metadata
        event_dict = self.mapper.to_mongo_document(event)
        event_dict["_deleted_at"] = datetime.now(timezone.utc)
        event_dict["_deleted_by"] = deleted_by

        # Insert into bound archive collection
        result = await self.events_archive_collection.insert_one(event_dict)
        return result.inserted_id is not None

    async def create_replay_session(self, session: ReplaySession) -> str:
        """Create a new replay session."""
        session_dict = self.replay_mapper.to_dict(session)
        await self.replay_sessions_collection.insert_one(session_dict)
        return session.session_id

    async def get_replay_session(self, session_id: str) -> ReplaySession | None:
        """Get replay session by ID."""
        doc = await self.replay_sessions_collection.find_one({ReplaySessionFields.SESSION_ID: session_id})
        return self.replay_mapper.from_dict(doc) if doc else None

    async def update_replay_session(self, session_id: str, updates: ReplaySessionUpdate) -> bool:
        """Update replay session fields."""
        if not updates.has_updates():
            return False

        mongo_updates = updates.to_dict()

        result = await self.replay_sessions_collection.update_one(
            {ReplaySessionFields.SESSION_ID: session_id}, {"$set": mongo_updates}
        )
        return result.modified_count > 0

    async def get_replay_status_with_progress(self, session_id: str) -> ReplaySessionStatusDetail | None:
        """Get replay session status with progress updates."""
        doc = await self.replay_sessions_collection.find_one({ReplaySessionFields.SESSION_ID: session_id})
        if not doc:
            return None

        session = self.replay_mapper.from_dict(doc)
        current_time = datetime.now(timezone.utc)

        # Update status based on time if needed
        if session.status == ReplayStatus.SCHEDULED and session.created_at:
            time_since_created = current_time - session.created_at
            if time_since_created.total_seconds() > 2:
                # Use atomic update to prevent race conditions
                update_result = await self.replay_sessions_collection.find_one_and_update(
                    {ReplaySessionFields.SESSION_ID: session_id, ReplaySessionFields.STATUS: ReplayStatus.SCHEDULED},
                    {
                        "$set": {
                            ReplaySessionFields.STATUS: ReplayStatus.RUNNING,
                            ReplaySessionFields.STARTED_AT: current_time,
                        }
                    },
                    return_document=ReturnDocument.AFTER,
                )
                if update_result:
                    # Update local session object with the atomically updated values
                    session = self.replay_mapper.from_dict(update_result)

        # Simulate progress if running
        if session.is_running and session.started_at:
            time_since_started = current_time - session.started_at
            # Assume 10 events per second processing rate
            estimated_progress = min(int(time_since_started.total_seconds() * 10), session.total_events)

            # Update progress - returns new instance
            updated_session = session.update_progress(estimated_progress)

            # Update in database
            session_update = ReplaySessionUpdate(replayed_events=updated_session.replayed_events)

            if updated_session.is_completed:
                session_update.status = updated_session.status
                session_update.completed_at = updated_session.completed_at

            await self.update_replay_session(session_id, session_update)

            # Use the updated session for the rest of the method
            session = updated_session

        # Calculate estimated completion
        estimated_completion = None
        if session.is_running and session.replayed_events > 0 and session.started_at:
            rate = session.replayed_events / (current_time - session.started_at).total_seconds()
            remaining = session.total_events - session.replayed_events
            if rate > 0:
                estimated_completion = current_time + timedelta(seconds=remaining / rate)

        # Fetch execution results from the original events that were replayed
        execution_results = []
        # Get the query that was used for replay from the session's config
        original_query = {}
        if doc and "config" in doc:
            config = doc.get("config", {})
            filter_config = config.get("filter", {})
            original_query = filter_config.get("custom_query", {})

        if original_query:
            # Find the original events that were replayed
            original_events = await self.events_collection.find(original_query).to_list(10)

            # Get unique execution IDs from original events
            execution_ids = set()
            for event in original_events:
                # Try to get execution_id from various locations
                exec_id = event.get("execution_id")
                if not exec_id and event.get("payload"):
                    exec_id = event.get("payload", {}).get("execution_id")
                if not exec_id:
                    exec_id = event.get("aggregate_id")
                if exec_id:
                    execution_ids.add(exec_id)

            # Fetch execution details
            if execution_ids:
                executions_collection = self.executions_collection
                for exec_id in list(execution_ids)[:10]:  # Limit to 10
                    exec_doc = await executions_collection.find_one({"execution_id": exec_id})
                    if exec_doc:
                        execution_results.append(
                            {
                                "execution_id": exec_doc.get("execution_id"),
                                "status": exec_doc.get("status"),
                                "stdout": exec_doc.get("stdout"),
                                "stderr": exec_doc.get("stderr"),
                                "exit_code": exec_doc.get("exit_code"),
                                "execution_time": exec_doc.get("execution_time"),
                                "lang": exec_doc.get("lang"),
                                "lang_version": exec_doc.get("lang_version"),
                                "created_at": exec_doc.get("created_at"),
                                "updated_at": exec_doc.get("updated_at"),
                            }
                        )

        return ReplaySessionStatusDetail(
            session=session, estimated_completion=estimated_completion, execution_results=execution_results
        )

    async def count_events_for_replay(self, query: Dict[str, Any]) -> int:
        """Count events matching replay query."""
        return await self.events_collection.count_documents(query)

    async def get_events_preview_for_replay(self, query: Dict[str, Any], limit: int = 100) -> List[Dict[str, Any]]:
        """Get preview of events for replay."""
        cursor = self.events_collection.find(query).limit(limit)
        event_docs = await cursor.to_list(length=limit)

        # Convert to event summaries
        summaries: List[Dict[str, Any]] = []
        for doc in event_docs:
            summary = self.summary_mapper.from_mongo_document(doc)
            summary_dict = self.summary_mapper.to_dict(summary)
            # Convert EventFields enum keys to strings
            summaries.append({str(k): v for k, v in summary_dict.items()})

        return summaries

    def build_replay_query(self, replay_query: ReplayQuery) -> Dict[str, Any]:
        """Build MongoDB query from replay query model."""
        return self.replay_query_mapper.to_mongodb_query(replay_query)

    async def prepare_replay_session(
        self, query: Dict[str, Any], dry_run: bool, replay_correlation_id: str, max_events: int = 1000
    ) -> ReplaySessionData:
        """Prepare replay session with validation and preview."""
        event_count = await self.count_events_for_replay(query)
        if event_count == 0:
            raise ValueError("No events found matching the criteria")
        if event_count > max_events and not dry_run:
            raise ValueError(f"Too many events to replay ({event_count}). Maximum is {max_events}.")

        # Get events preview for dry run
        events_preview: List[EventSummary] = []
        if dry_run:
            preview_docs = await self.get_events_preview_for_replay(query, limit=100)
            events_preview = [self.summary_mapper.from_mongo_document(e) for e in preview_docs]

        # Return unified session data
        session_data = ReplaySessionData(
            total_events=event_count,
            replay_correlation_id=replay_correlation_id,
            dry_run=dry_run,
            query=query,
            events_preview=events_preview,
        )

        return session_data

    async def get_replay_events_preview(
        self, event_ids: List[str] | None = None, correlation_id: str | None = None, aggregate_id: str | None = None
    ) -> Dict[str, Any]:
        """Get preview of events that would be replayed - backward compatibility."""
        replay_query = ReplayQuery(event_ids=event_ids, correlation_id=correlation_id, aggregate_id=aggregate_id)

        query = self.replay_query_mapper.to_mongodb_query(replay_query)

        if not query:
            return {"events": [], "total": 0}

        total = await self.event_store_collection.count_documents(query)

        cursor = self.event_store_collection.find(query).sort(EventFields.TIMESTAMP, SortDirection.ASCENDING).limit(100)

        # Batch fetch all events from cursor
        events = await cursor.to_list(length=100)

        return {"events": events, "total": total}
