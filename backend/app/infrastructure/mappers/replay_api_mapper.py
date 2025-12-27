from __future__ import annotations

from app.domain.enums.replay import ReplayStatus
from app.domain.replay import ReplayConfig, ReplayFilter, ReplaySessionState
from app.schemas_pydantic.replay import CleanupResponse, ReplayRequest, ReplayResponse, SessionSummary


class ReplayApiMapper:
    @staticmethod
    def session_to_summary(state: ReplaySessionState) -> SessionSummary:
        duration = None
        throughput = None
        if state.started_at and state.completed_at:
            d = (state.completed_at - state.started_at).total_seconds()
            duration = d
            if state.replayed_events > 0 and d > 0:
                throughput = state.replayed_events / d
        return SessionSummary(
            session_id=state.session_id,
            replay_type=state.config.replay_type,
            target=state.config.target,
            status=state.status,
            total_events=state.total_events,
            replayed_events=state.replayed_events,
            failed_events=state.failed_events,
            skipped_events=state.skipped_events,
            created_at=state.created_at,
            started_at=state.started_at,
            completed_at=state.completed_at,
            duration_seconds=duration,
            throughput_events_per_second=throughput,
        )

    # Request/Response mapping for HTTP
    @staticmethod
    def request_to_filter(req: ReplayRequest) -> ReplayFilter:
        return ReplayFilter(
            execution_id=req.execution_id,
            event_types=req.event_types,
            start_time=req.start_time if req.start_time else None,
            end_time=req.end_time if req.end_time else None,
            user_id=req.user_id,
            service_name=req.service_name,
            custom_query=req.custom_query,
            exclude_event_types=req.exclude_event_types,
        )

    @staticmethod
    def request_to_config(req: ReplayRequest) -> ReplayConfig:
        # Convert string keys to EventType for target_topics if provided
        target_topics = None
        if req.target_topics:
            from app.domain.enums.events import EventType

            target_topics = {EventType(k): v for k, v in req.target_topics.items()}

        return ReplayConfig(
            replay_type=req.replay_type,
            target=req.target,
            filter=ReplayApiMapper.request_to_filter(req),
            speed_multiplier=req.speed_multiplier,
            preserve_timestamps=req.preserve_timestamps,
            batch_size=req.batch_size,
            max_events=req.max_events,
            skip_errors=req.skip_errors,
            target_file_path=req.target_file_path,
            target_topics=target_topics,
            retry_failed=req.retry_failed,
            retry_attempts=req.retry_attempts,
            enable_progress_tracking=req.enable_progress_tracking,
        )

    @staticmethod
    def op_to_response(session_id: str, status: ReplayStatus, message: str) -> ReplayResponse:
        return ReplayResponse(session_id=session_id, status=status, message=message)

    @staticmethod
    def cleanup_to_response(removed_sessions: int, message: str) -> CleanupResponse:
        return CleanupResponse(removed_sessions=removed_sessions, message=message)
