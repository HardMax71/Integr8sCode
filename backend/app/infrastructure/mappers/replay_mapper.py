from datetime import datetime, timezone
from typing import Any

from app.domain.admin.replay_models import (
    ReplayQuery,
    ReplaySession,
    ReplaySessionData,
    ReplaySessionFields,
    ReplaySessionStatus,
    ReplaySessionStatusDetail,
    ReplaySessionStatusInfo,
)
from app.domain.events.event_models import EventFields


class ReplaySessionMapper:
    @staticmethod
    def to_dict(session: ReplaySession) -> dict[str, Any]:
        doc: dict[str, Any] = {
            ReplaySessionFields.SESSION_ID: session.session_id,
            ReplaySessionFields.TYPE: session.type,
            ReplaySessionFields.STATUS: session.status,
            ReplaySessionFields.TOTAL_EVENTS: session.total_events,
            ReplaySessionFields.REPLAYED_EVENTS: session.replayed_events,
            ReplaySessionFields.FAILED_EVENTS: session.failed_events,
            ReplaySessionFields.SKIPPED_EVENTS: session.skipped_events,
            ReplaySessionFields.CORRELATION_ID: session.correlation_id,
            ReplaySessionFields.CREATED_AT: session.created_at,
            ReplaySessionFields.DRY_RUN: session.dry_run,
            "triggered_executions": session.triggered_executions
        }
        
        if session.started_at:
            doc[ReplaySessionFields.STARTED_AT] = session.started_at
        if session.completed_at:
            doc[ReplaySessionFields.COMPLETED_AT] = session.completed_at
        if session.error:
            doc[ReplaySessionFields.ERROR] = session.error
        if session.created_by:
            doc[ReplaySessionFields.CREATED_BY] = session.created_by
        if session.target_service:
            doc[ReplaySessionFields.TARGET_SERVICE] = session.target_service
        
        return doc
    
    @staticmethod
    def from_dict(data: dict[str, Any]) -> ReplaySession:
        return ReplaySession(
            session_id=data.get(ReplaySessionFields.SESSION_ID, ""),
            type=data.get(ReplaySessionFields.TYPE, "replay_session"),
            status=ReplaySessionStatus(data.get(ReplaySessionFields.STATUS, ReplaySessionStatus.SCHEDULED)),
            total_events=data.get(ReplaySessionFields.TOTAL_EVENTS, 0),
            replayed_events=data.get(ReplaySessionFields.REPLAYED_EVENTS, 0),
            failed_events=data.get(ReplaySessionFields.FAILED_EVENTS, 0),
            skipped_events=data.get(ReplaySessionFields.SKIPPED_EVENTS, 0),
            correlation_id=data.get(ReplaySessionFields.CORRELATION_ID, ""),
            created_at=data.get(ReplaySessionFields.CREATED_AT, datetime.now(timezone.utc)),
            started_at=data.get(ReplaySessionFields.STARTED_AT),
            completed_at=data.get(ReplaySessionFields.COMPLETED_AT),
            error=data.get(ReplaySessionFields.ERROR),
            created_by=data.get(ReplaySessionFields.CREATED_BY),
            target_service=data.get(ReplaySessionFields.TARGET_SERVICE),
            dry_run=data.get(ReplaySessionFields.DRY_RUN, False),
            triggered_executions=data.get("triggered_executions", [])
        )
    
    @staticmethod
    def status_detail_to_dict(detail: ReplaySessionStatusDetail) -> dict[str, Any]:
        result = {
            "session_id": detail.session.session_id,
            "status": detail.session.status.value,
            "total_events": detail.session.total_events,
            "replayed_events": detail.session.replayed_events,
            "failed_events": detail.session.failed_events,
            "skipped_events": detail.session.skipped_events,
            "correlation_id": detail.session.correlation_id,
            "created_at": detail.session.created_at,
            "started_at": detail.session.started_at,
            "completed_at": detail.session.completed_at,
            "error": detail.session.error,
            "progress_percentage": detail.session.progress_percentage,
            "execution_results": detail.execution_results
        }
        
        if detail.estimated_completion:
            result["estimated_completion"] = detail.estimated_completion
        
        return result

    @staticmethod
    def to_status_info(session: ReplaySession) -> ReplaySessionStatusInfo:
        return ReplaySessionStatusInfo(
            session_id=session.session_id,
            status=session.status,
            total_events=session.total_events,
            replayed_events=session.replayed_events,
            failed_events=session.failed_events,
            skipped_events=session.skipped_events,
            correlation_id=session.correlation_id,
            created_at=session.created_at,
            started_at=session.started_at,
            completed_at=session.completed_at,
            error=session.error,
            progress_percentage=session.progress_percentage,
        )

    @staticmethod
    def status_info_to_dict(info: ReplaySessionStatusInfo) -> dict[str, Any]:
        return {
            "session_id": info.session_id,
            "status": info.status.value,
            "total_events": info.total_events,
            "replayed_events": info.replayed_events,
            "failed_events": info.failed_events,
            "skipped_events": info.skipped_events,
            "correlation_id": info.correlation_id,
            "created_at": info.created_at,
            "started_at": info.started_at,
            "completed_at": info.completed_at,
            "error": info.error,
            "progress_percentage": info.progress_percentage,
        }


class ReplayQueryMapper:
    @staticmethod
    def to_mongodb_query(query: ReplayQuery) -> dict[str, Any]:
        mongo_query: dict[str, Any] = {}
        
        if query.event_ids:
            mongo_query[EventFields.EVENT_ID] = {"$in": query.event_ids}
        
        if query.correlation_id:
            mongo_query[EventFields.METADATA_CORRELATION_ID] = query.correlation_id
        
        if query.aggregate_id:
            mongo_query[EventFields.AGGREGATE_ID] = query.aggregate_id
        
        if query.start_time or query.end_time:
            time_query = {}
            if query.start_time:
                time_query["$gte"] = query.start_time
            if query.end_time:
                time_query["$lte"] = query.end_time
            mongo_query[EventFields.TIMESTAMP] = time_query
        
        return mongo_query


class ReplaySessionDataMapper:
    @staticmethod
    def to_dict(data: ReplaySessionData) -> dict[str, Any]:
        result = {
            "dry_run": data.dry_run,
            "total_events": data.total_events,
            "replay_correlation_id": data.replay_correlation_id,
            "query": data.query
        }
        
        if data.dry_run and data.events_preview:
            result["events_preview"] = [
                {
                    "event_id": e.event_id,
                    "event_type": e.event_type,
                    "timestamp": e.timestamp,
                    "aggregate_id": e.aggregate_id
                }
                for e in data.events_preview
            ]
        
        return result
