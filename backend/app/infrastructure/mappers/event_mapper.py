from datetime import datetime, timezone
from typing import Any

from app.domain.events.event_models import (
    ArchivedEvent,
    Event,
    EventBrowseResult,
    EventDetail,
    EventExportRow,
    EventFields,
    EventFilter,
    EventListResult,
    EventProjection,
    EventReplayInfo,
    EventStatistics,
    EventSummary,
    HourlyEventCount,
)
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.schemas_pydantic.admin_events import EventFilter as AdminEventFilter


class EventMapper:
    """Handles all Event serialization/deserialization."""
    
    @staticmethod
    def to_mongo_document(event: Event) -> dict[str, Any]:
        """Convert domain event to MongoDB document."""
        doc: dict[str, Any] = {
            EventFields.EVENT_ID: event.event_id,
            EventFields.EVENT_TYPE: event.event_type,
            EventFields.EVENT_VERSION: event.event_version,
            EventFields.TIMESTAMP: event.timestamp,
            EventFields.METADATA: event.metadata.to_dict(),
            EventFields.PAYLOAD: event.payload
        }
        
        if event.aggregate_id is not None:
            doc[EventFields.AGGREGATE_ID] = event.aggregate_id
        if event.stored_at is not None:
            doc[EventFields.STORED_AT] = event.stored_at
        if event.ttl_expires_at is not None:
            doc[EventFields.TTL_EXPIRES_AT] = event.ttl_expires_at
        if event.status is not None:
            doc[EventFields.STATUS] = event.status
        if event.error is not None:
            doc[EventFields.ERROR] = event.error
            
        return doc
    
    @staticmethod
    def from_mongo_document(document: dict[str, Any]) -> Event:
        """Create domain event from MongoDB document."""
        # Define base event fields that should NOT be in payload
        base_fields = {
            EventFields.EVENT_ID, EventFields.EVENT_TYPE, EventFields.EVENT_VERSION,
            EventFields.TIMESTAMP, EventFields.METADATA, EventFields.AGGREGATE_ID,
            EventFields.STORED_AT, EventFields.TTL_EXPIRES_AT, EventFields.STATUS,
            EventFields.ERROR, "_id", "stored_at"
        }
        
        # Extract all non-base fields as payload
        payload = {k: v for k, v in document.items() if k not in base_fields}
        
        return Event(
            event_id=document[EventFields.EVENT_ID],
            event_type=document[EventFields.EVENT_TYPE],
            event_version=document.get(EventFields.EVENT_VERSION, "1.0"),
            timestamp=document.get(EventFields.TIMESTAMP, datetime.now(timezone.utc)),
            metadata=EventMetadata.from_dict(document.get(EventFields.METADATA, {})),
            payload=payload,
            aggregate_id=document.get(EventFields.AGGREGATE_ID),
            stored_at=document.get(EventFields.STORED_AT),
            ttl_expires_at=document.get(EventFields.TTL_EXPIRES_AT),
            status=document.get(EventFields.STATUS),
            error=document.get(EventFields.ERROR)
        )
    
    @staticmethod
    def to_dict(event: Event) -> dict[str, Any]:
        """Convert event to API response dictionary."""
        result: dict[str, Any] = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "event_version": event.event_version,
            "timestamp": event.timestamp,
            "metadata": event.metadata.to_dict(),
            "payload": event.payload
        }
        
        if event.aggregate_id is not None:
            result["aggregate_id"] = event.aggregate_id
        if event.correlation_id:
            result["correlation_id"] = event.correlation_id
        if event.stored_at is not None:
            result["stored_at"] = event.stored_at
        if event.ttl_expires_at is not None:
            result["ttl_expires_at"] = event.ttl_expires_at
        if event.status is not None:
            result["status"] = event.status
        if event.error is not None:
            result["error"] = event.error
            
        return result
    
    @staticmethod
    def from_dict(data: dict[str, Any]) -> Event:
        """Create event from API request dictionary."""
        return Event(
            event_id=data["event_id"],
            event_type=data["event_type"],
            event_version=data.get("event_version", "1.0"),
            timestamp=data.get("timestamp", datetime.now(timezone.utc)),
            metadata=EventMetadata.from_dict(data.get("metadata", {})),
            payload=data.get("payload", {}),
            aggregate_id=data.get("aggregate_id"),
            stored_at=data.get("stored_at"),
            ttl_expires_at=data.get("ttl_expires_at"),
            status=data.get("status"),
            error=data.get("error")
        )


class EventSummaryMapper:
    """Handles EventSummary serialization."""
    
    @staticmethod
    def to_dict(summary: EventSummary) -> dict[EventFields, Any]:
        result = {
            EventFields.EVENT_ID: summary.event_id,
            EventFields.EVENT_TYPE: summary.event_type,
            EventFields.TIMESTAMP: summary.timestamp
        }
        if summary.aggregate_id is not None:
            result[EventFields.AGGREGATE_ID] = summary.aggregate_id
        return result
    
    @staticmethod
    def from_mongo_document(document: dict[str, Any]) -> EventSummary:
        return EventSummary(
            event_id=document[EventFields.EVENT_ID],
            event_type=document[EventFields.EVENT_TYPE],
            timestamp=document[EventFields.TIMESTAMP],
            aggregate_id=document.get(EventFields.AGGREGATE_ID)
        )


class EventDetailMapper:
    """Handles EventDetail serialization."""
    
    @staticmethod
    def to_dict(detail: EventDetail) -> dict[str, Any]:
        event_mapper = EventMapper()
        summary_mapper = EventSummaryMapper()
        
        return {
            "event": event_mapper.to_dict(detail.event),
            "related_events": [summary_mapper.to_dict(e) for e in detail.related_events],
            "timeline": [summary_mapper.to_dict(e) for e in detail.timeline]
        }


class EventListResultMapper:
    """Handles EventListResult serialization."""
    
    @staticmethod
    def to_dict(result: EventListResult) -> dict[str, Any]:
        event_mapper = EventMapper()
        return {
            "events": [event_mapper.to_dict(event) for event in result.events],
            "total": result.total,
            "skip": result.skip,
            "limit": result.limit,
            "has_more": result.has_more
        }


class EventBrowseResultMapper:
    """Handles EventBrowseResult serialization."""
    
    @staticmethod
    def to_dict(result: EventBrowseResult) -> dict[str, Any]:
        event_mapper = EventMapper()
        return {
            "events": [event_mapper.to_dict(event) for event in result.events],
            "total": result.total,
            "skip": result.skip,
            "limit": result.limit
        }


class EventStatisticsMapper:
    """Handles EventStatistics serialization."""
    
    @staticmethod
    def to_dict(stats: EventStatistics) -> dict[str, Any]:
        result: dict[str, Any] = {
            "total_events": stats.total_events,
            "events_by_type": stats.events_by_type,
            "events_by_service": stats.events_by_service,
            "events_by_hour": [
                {"hour": h.hour, "count": h.count} if isinstance(h, HourlyEventCount) else h
                for h in stats.events_by_hour
            ],
            "top_users": [
                {"user_id": u.user_id, "event_count": u.event_count}
                for u in stats.top_users
            ],
            "error_rate": stats.error_rate,
            "avg_processing_time": stats.avg_processing_time
        }
        
        if stats.start_time is not None:
            result["start_time"] = stats.start_time
        if stats.end_time is not None:
            result["end_time"] = stats.end_time
            
        return result


class EventProjectionMapper:
    """Handles EventProjection serialization."""
    
    @staticmethod
    def to_dict(projection: EventProjection) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": projection.name,
            "pipeline": projection.pipeline,
            "output_collection": projection.output_collection,
            "refresh_interval_seconds": projection.refresh_interval_seconds
        }
        
        if projection.description is not None:
            result["description"] = projection.description
        if projection.source_events is not None:
            result["source_events"] = projection.source_events
        if projection.last_updated is not None:
            result["last_updated"] = projection.last_updated
            
        return result


class ArchivedEventMapper:
    """Handles ArchivedEvent serialization."""
    
    @staticmethod
    def to_mongo_document(event: ArchivedEvent) -> dict[str, Any]:
        event_mapper = EventMapper()
        doc = event_mapper.to_mongo_document(event)
        
        if event.deleted_at is not None:
            doc[EventFields.DELETED_AT] = event.deleted_at
        if event.deleted_by is not None:
            doc[EventFields.DELETED_BY] = event.deleted_by
        if event.deletion_reason is not None:
            doc[EventFields.DELETION_REASON] = event.deletion_reason
            
        return doc
    
    @staticmethod
    def from_event(event: Event, deleted_by: str, deletion_reason: str) -> ArchivedEvent:
        return ArchivedEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            event_version=event.event_version,
            timestamp=event.timestamp,
            metadata=event.metadata,
            payload=event.payload,
            aggregate_id=event.aggregate_id,
            stored_at=event.stored_at,
            ttl_expires_at=event.ttl_expires_at,
            status=event.status,
            error=event.error,
            deleted_at=datetime.now(timezone.utc),
            deleted_by=deleted_by,
            deletion_reason=deletion_reason
        )


class EventExportRowMapper:
    """Handles EventExportRow serialization."""
    
    @staticmethod
    def to_dict(row: EventExportRow) -> dict[str, str]:
        return {
            "Event ID": row.event_id,
            "Event Type": row.event_type,
            "Timestamp": row.timestamp,
            "Correlation ID": row.correlation_id,
            "Aggregate ID": row.aggregate_id,
            "User ID": row.user_id,
            "Service": row.service,
            "Status": row.status,
            "Error": row.error
        }

    @staticmethod
    def from_event(event: Event) -> EventExportRow:
        return EventExportRow(
            event_id=event.event_id,
            event_type=event.event_type,
            timestamp=event.timestamp.isoformat(),
            correlation_id=event.metadata.correlation_id or "",
            aggregate_id=event.aggregate_id or "",
            user_id=event.metadata.user_id or "",
            service=event.metadata.service_name,
            status=event.status or "",
            error=event.error or "",
        )


class EventFilterMapper:
    """Converts EventFilter domain model into MongoDB queries."""

    @staticmethod
    def to_mongo_query(flt: EventFilter) -> dict[str, Any]:
        query: dict[str, Any] = {}

        if flt.event_types:
            query[EventFields.EVENT_TYPE] = {"$in": flt.event_types}
        if flt.aggregate_id:
            query[EventFields.AGGREGATE_ID] = flt.aggregate_id
        if flt.correlation_id:
            query[EventFields.METADATA_CORRELATION_ID] = flt.correlation_id
        if flt.user_id:
            query[EventFields.METADATA_USER_ID] = flt.user_id
        if flt.service_name:
            query[EventFields.METADATA_SERVICE_NAME] = flt.service_name
        if getattr(flt, "status", None):
            query[EventFields.STATUS] = flt.status

        if flt.start_time or flt.end_time:
            time_query: dict[str, Any] = {}
            if flt.start_time:
                time_query["$gte"] = flt.start_time
            if flt.end_time:
                time_query["$lte"] = flt.end_time
            query[EventFields.TIMESTAMP] = time_query

        search = getattr(flt, "text_search", None) or getattr(flt, "search_text", None)
        if search:
            query["$text"] = {"$search": search}

        return query

    @staticmethod
    def from_admin_pydantic(pflt: AdminEventFilter) -> EventFilter:
        ev_types: list[str] | None = None
        if pflt.event_types is not None:
            ev_types = [str(et) for et in pflt.event_types]
        return EventFilter(
            event_types=ev_types,
            aggregate_id=pflt.aggregate_id,
            correlation_id=pflt.correlation_id,
            user_id=pflt.user_id,
            service_name=pflt.service_name,
            start_time=pflt.start_time,
            end_time=pflt.end_time,
            search_text=pflt.search_text,
            text_search=pflt.search_text,
        )


class EventReplayInfoMapper:
    """Handles EventReplayInfo serialization."""
    
    @staticmethod
    def to_dict(info: EventReplayInfo) -> dict[str, Any]:
        event_mapper = EventMapper()
        return {
            "events": [event_mapper.to_dict(event) for event in info.events],
            "event_count": info.event_count,
            "event_types": info.event_types,
            "start_time": info.start_time,
            "end_time": info.end_time
        }
