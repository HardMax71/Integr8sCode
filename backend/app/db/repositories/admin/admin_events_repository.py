"""Admin events repository with domain models.

This module provides data access for admin event operations using strongly-typed domain models
instead of Dict[str, Any] for improved type safety and maintainability.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Request
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.core.logging import logger
from app.db.mongodb import DatabaseManager
from app.domain.admin.event_models import (
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
from app.domain.admin.query_builders import (
    EventStatsAggregation,
)
from app.domain.admin.replay_models import (
    ReplayQuery,
    ReplaySession,
    ReplaySessionData,
    ReplaySessionFields,
    ReplaySessionStatus,
    ReplaySessionStatusDetail,
)


class AdminEventsRepository:
    """Repository for admin event operations using domain models."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.events_collection: AsyncIOMotorCollection = self.db.get_collection(CollectionNames.EVENTS)
        self.event_store_collection: AsyncIOMotorCollection = self.db.get_collection(CollectionNames.EVENT_STORE)
        self.replay_sessions_collection: AsyncIOMotorCollection = self.db.get_collection(
            CollectionNames.REPLAY_SESSIONS)

    async def browse_events(
            self,
            filter: EventFilter,
            skip: int = 0,
            limit: int = 50,
            sort_by: str = EventFields.TIMESTAMP,
            sort_order: int = SortDirection.DESCENDING
    ) -> EventBrowseResult:
        """Browse events with filters using domain models."""
        try:

            # Convert filter to MongoDB query
            query = filter.to_query()

            # Get total count
            total = await self.events_collection.count_documents(query)

            # Execute query with pagination
            cursor = self.events_collection.find(query)
            cursor = cursor.sort(sort_by, sort_order)
            cursor = cursor.skip(skip).limit(limit)

            # Fetch events and convert to domain models
            event_docs = await cursor.to_list(length=limit)
            events = [Event.from_dict(doc) for doc in event_docs]

            return EventBrowseResult(
                events=events,
                total=total,
                skip=skip,
                limit=limit
            )
        except Exception as e:
            logger.error(f"Error browsing events: {e}")
            raise

    async def get_event_detail(self, event_id: str) -> Optional[EventDetail]:
        """Get detailed information about an event."""
        try:
            # Find event by ID
            event_doc = await self.events_collection.find_one({EventFields.EVENT_ID: event_id})

            if not event_doc:
                return None

            event = Event.from_dict(event_doc)

            # Get related events if correlation ID exists
            related_events: List[EventSummary] = []
            if event.correlation_id:
                cursor = self.events_collection.find({
                    EventFields.CORRELATION_ID: event.correlation_id,
                    EventFields.EVENT_ID: {"$ne": event_id}
                }).sort(EventFields.TIMESTAMP, SortDirection.ASCENDING).limit(10)

                related_docs = await cursor.to_list(length=10)
                related_events = [EventSummary.from_dict(doc) for doc in related_docs]

            # Build timeline (could be expanded with more logic)
            timeline = related_events[:5]  # Simple timeline for now

            detail = EventDetail(
                event=event,
                related_events=related_events,
                timeline=timeline
            )

            return detail

        except Exception as e:
            logger.error(f"Error getting event detail: {e}")
            raise

    async def delete_event(self, event_id: str) -> bool:
        """Delete an event."""
        try:
            result = await self.events_collection.delete_one({EventFields.EVENT_ID: event_id})
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"Error deleting event: {e}")
            raise

    async def get_event_stats(self, hours: int = 24) -> EventStatistics:
        """Get event statistics for the last N hours."""
        try:
            start_time = datetime.now(timezone.utc) - timedelta(hours=hours)

            # Get overview statistics
            overview_pipeline = EventStatsAggregation.build_overview_pipeline(start_time)
            overview_result = await self.events_collection.aggregate(overview_pipeline).to_list(1)

            stats = overview_result[0] if overview_result else {
                "total_events": 0,
                "event_type_count": 0,
                "unique_user_count": 0,
                "service_count": 0
            }

            # Get error rate
            error_count = await self.events_collection.count_documents({
                EventFields.TIMESTAMP: {"$gte": start_time},
                EventFields.EVENT_TYPE: {"$regex": "failed|error", "$options": "i"}
            })

            error_rate = (error_count / stats["total_events"] * 100) if stats["total_events"] > 0 else 0

            # Get event types with counts
            type_pipeline = EventStatsAggregation.build_event_types_pipeline(start_time)
            top_types = await self.events_collection.aggregate(type_pipeline).to_list(10)
            events_by_type = {t["_id"]: t["count"] for t in top_types}

            # Get events by hour
            hourly_pipeline = EventStatsAggregation.build_hourly_events_pipeline(start_time)
            hourly_cursor = self.events_collection.aggregate(hourly_pipeline)
            events_by_hour = [
                HourlyEventCount(hour=doc["_id"], count=doc["count"])
                async for doc in hourly_cursor
            ]

            # Get top users
            user_pipeline = EventStatsAggregation.build_top_users_pipeline(start_time)
            top_users_cursor = self.events_collection.aggregate(user_pipeline)
            top_users = [
                UserEventCount(user_id=doc["_id"], event_count=doc["count"])
                async for doc in top_users_cursor
                if doc["_id"]  # Filter out None user_ids
            ]

            # Get average processing time
            from app.schemas_avro.event_schemas import EventType
            exec_pipeline = EventStatsAggregation.build_avg_duration_pipeline(
                start_time,
                str(EventType.EXECUTION_COMPLETED)
            )
            exec_result = await self.events_collection.aggregate(exec_pipeline).to_list(1)
            avg_processing_time = exec_result[0]["avg_duration"] if exec_result else 0

            statistics = EventStatistics(
                total_events=stats["total_events"],
                events_by_type=events_by_type,
                events_by_hour=events_by_hour,
                top_users=top_users,
                error_rate=round(error_rate, 2),
                avg_processing_time=round(avg_processing_time, 2)
            )

            return statistics

        except Exception as e:
            logger.error(f"Error getting event stats: {e}")
            raise

    async def export_events_csv(self, filter: EventFilter) -> List[EventExportRow]:
        """Export events as CSV data."""
        try:

            query = filter.to_query()

            cursor = self.events_collection.find(query).sort(
                EventFields.TIMESTAMP,
                SortDirection.DESCENDING
            ).limit(10000)

            event_docs = await cursor.to_list(length=10000)

            # Convert to export rows
            export_rows = []
            for doc in event_docs:
                event = Event.from_dict(doc)
                export_row = EventExportRow.from_event(event)
                export_rows.append(export_row)

            return export_rows

        except Exception as e:
            logger.error(f"Error exporting events: {e}")
            raise

    async def archive_event(self, event: Event, deleted_by: str) -> bool:
        """Archive an event before deletion."""
        try:

            # Add deletion metadata
            event_dict = event.to_dict()
            event_dict["_deleted_at"] = datetime.now(timezone.utc)
            event_dict["_deleted_by"] = deleted_by

            # Create events_archive collection if it doesn't exist
            events_archive = self.db.get_collection(CollectionNames.EVENTS_ARCHIVE)
            await events_archive.insert_one(event_dict)
            return True
        except Exception as e:
            logger.error(f"Error archiving event: {e}")
            raise

    async def create_replay_session(self, session: ReplaySession) -> str:
        """Create a new replay session."""
        try:

            session_dict = session.to_dict()
            await self.replay_sessions_collection.insert_one(session_dict)
            return session.session_id
        except Exception as e:
            logger.error(f"Error creating replay session: {e}")
            raise

    async def get_replay_session(self, session_id: str) -> Optional[ReplaySession]:
        """Get replay session by ID."""
        try:
            doc = await self.replay_sessions_collection.find_one({
                ReplaySessionFields.SESSION_ID: session_id
            })
            return ReplaySession.from_dict(doc) if doc else None
        except Exception as e:
            logger.error(f"Error getting replay session: {e}")
            raise

    async def update_replay_session(self, session_id: str, updates: Dict[str, Any]) -> bool:
        """Update replay session fields."""
        try:
            result = await self.replay_sessions_collection.update_one(
                {ReplaySessionFields.SESSION_ID: session_id},
                {"$set": updates}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error updating replay session: {e}")
            raise

    async def get_replay_status_with_progress(self, session_id: str) -> Optional[ReplaySessionStatusDetail]:
        """Get replay session status with progress updates."""
        try:
            doc = await self.replay_sessions_collection.find_one({
                ReplaySessionFields.SESSION_ID: session_id
            })

            if not doc:
                return None

            session = ReplaySession.from_dict(doc)
            current_time = datetime.now(timezone.utc)

            # Update status based on time if needed
            if session.status == ReplaySessionStatus.SCHEDULED and session.created_at:
                time_since_created = current_time - session.created_at
                if time_since_created.total_seconds() > 2:
                    session.status = ReplaySessionStatus.RUNNING
                    session.started_at = current_time
                    await self.update_replay_session(
                        session_id,
                        {
                            ReplaySessionFields.STATUS: session.status.value,
                            ReplaySessionFields.STARTED_AT: session.started_at
                        }
                    )

            # Simulate progress if running
            if session.is_running and session.started_at:
                time_since_started = current_time - session.started_at
                # Assume 10 events per second processing rate
                estimated_progress = min(
                    int(time_since_started.total_seconds() * 10),
                    session.total_events
                )

                session.update_progress(estimated_progress)

                # Update in database
                updates: Dict[str, Any] = {
                    str(ReplaySessionFields.REPLAYED_EVENTS): session.replayed_events
                }

                if session.is_completed:
                    updates[str(ReplaySessionFields.STATUS)] = session.status.value
                    updates[str(ReplaySessionFields.COMPLETED_AT)] = session.completed_at

                await self.update_replay_session(session_id, updates)

            # Calculate estimated completion
            estimated_completion = None
            if session.is_running and session.replayed_events > 0 and session.started_at:
                rate = session.replayed_events / (current_time - session.started_at).total_seconds()
                remaining = session.total_events - session.replayed_events
                if rate > 0:
                    estimated_completion = current_time + timedelta(seconds=remaining / rate)

            status_detail = ReplaySessionStatusDetail(
                session=session,
                estimated_completion=estimated_completion
            )

            return status_detail

        except Exception as e:
            logger.error(f"Error getting replay status with progress: {e}")
            raise

    async def count_events_for_replay(self, query: Dict[str, Any]) -> int:
        """Count events matching replay query."""
        try:
            return await self.events_collection.count_documents(query)
        except Exception as e:
            logger.error(f"Error counting events for replay: {e}")
            raise

    async def get_events_preview_for_replay(self, query: Dict[str, Any], limit: int = 100) -> List[Dict[str, Any]]:
        """Get preview of events for replay."""
        try:
            cursor = self.events_collection.find(query).limit(limit)
            event_docs = await cursor.to_list(length=limit)

            # Convert to event summaries
            summaries = []
            for doc in event_docs:
                summary = EventSummary.from_dict(doc)
                summaries.append(summary.to_dict())

            return summaries
        except Exception as e:
            logger.error(f"Error getting events preview: {e}")
            raise

    def build_replay_query(self, replay_query: ReplayQuery) -> Dict[str, Any]:
        """Build MongoDB query from replay query model."""
        return replay_query.to_mongodb_query()

    async def prepare_replay_session(
            self,
            query: Dict[str, Any],
            dry_run: bool,
            replay_correlation_id: str,
            max_events: int = 1000
    ) -> ReplaySessionData:
        """Prepare replay session with validation and preview."""
        try:
            # Count matching events
            event_count = await self.count_events_for_replay(query)

            if event_count == 0:
                raise ValueError("No events found matching the criteria")

            if event_count > max_events and not dry_run:
                raise ValueError(f"Too many events to replay ({event_count}). Maximum is {max_events}.")

            # Get events preview for dry run
            events_preview: List[EventSummary] = []
            if dry_run:
                preview_docs = await self.get_events_preview_for_replay(query, limit=100)
                events_preview = [EventSummary.from_dict(e) for e in preview_docs]

            # Return unified session data
            session_data = ReplaySessionData(
                total_events=event_count,
                replay_correlation_id=replay_correlation_id,
                dry_run=dry_run,
                query=query,
                events_preview=events_preview
            )

            return session_data

        except Exception as e:
            logger.error(f"Error preparing replay session: {e}")
            raise

    async def get_replay_events_preview(
            self,
            event_ids: Optional[List[str]] = None,
            correlation_id: Optional[str] = None,
            aggregate_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get preview of events that would be replayed - backward compatibility."""
        try:
            replay_query = ReplayQuery(
                event_ids=event_ids,
                correlation_id=correlation_id,
                aggregate_id=aggregate_id
            )

            query = replay_query.to_mongodb_query()

            if not query:
                return {"events": [], "total": 0}

            total = await self.event_store_collection.count_documents(query)

            cursor = self.event_store_collection.find(query).sort(
                EventFields.TIMESTAMP,
                SortDirection.ASCENDING
            ).limit(100)

            # Batch fetch all events from cursor
            events = await cursor.to_list(length=100)

            return {
                "events": events,
                "total": total
            }

        except Exception as e:
            logger.error(f"Error getting replay preview: {e}")
            raise


def get_admin_events_repository(request: Request) -> AdminEventsRepository:
    """FastAPI dependency to get admin events repository."""
    db_manager: DatabaseManager = request.app.state.db_manager
    return AdminEventsRepository(db_manager.get_database())
