from __future__ import annotations

from app.domain.enums.replay import ReplayStatus
from app.domain.replay.models import ReplayConfig, ReplayFilter, ReplaySessionState
from app.schemas_pydantic.replay import CleanupResponse, ReplayRequest, ReplayResponse, SessionSummary
from app.schemas_pydantic.replay_models import (
    ReplayConfigSchema,
    ReplayFilterSchema,
    ReplaySession,
)


class ReplayApiMapper:
    @staticmethod
    def filter_to_schema(f: ReplayFilter) -> ReplayFilterSchema:
        return ReplayFilterSchema(
            execution_id=f.execution_id,
            event_types=[str(et) for et in f.event_types] if f.event_types else None,
            start_time=f.start_time,
            end_time=f.end_time,
            user_id=f.user_id,
            service_name=f.service_name,
            custom_query=f.custom_query,
            exclude_event_types=[str(et) for et in f.exclude_event_types] if f.exclude_event_types else None,
        )

    @staticmethod
    def config_to_schema(c: ReplayConfig) -> ReplayConfigSchema:
        return ReplayConfigSchema(
            replay_type=c.replay_type,
            target=c.target,
            filter=ReplayApiMapper.filter_to_schema(c.filter),
            speed_multiplier=c.speed_multiplier,
            preserve_timestamps=c.preserve_timestamps,
            batch_size=c.batch_size,
            max_events=c.max_events,
            target_topics={str(k): v for k, v in (c.target_topics or {}).items()},
            target_file_path=c.target_file_path,
            skip_errors=c.skip_errors,
            retry_failed=c.retry_failed,
            retry_attempts=c.retry_attempts,
            enable_progress_tracking=c.enable_progress_tracking,
        )

    @staticmethod
    def session_to_response(state: ReplaySessionState) -> ReplaySession:
        return ReplaySession(
            session_id=state.session_id,
            config=ReplayApiMapper.config_to_schema(state.config),
            status=state.status,
            total_events=state.total_events,
            replayed_events=state.replayed_events,
            failed_events=state.failed_events,
            skipped_events=state.skipped_events,
            created_at=state.created_at,
            started_at=state.started_at,
            completed_at=state.completed_at,
            last_event_at=state.last_event_at,
            errors=state.errors,
        )

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
            start_time=req.start_time.timestamp() if req.start_time else None,
            end_time=req.end_time.timestamp() if req.end_time else None,
            user_id=req.user_id,
            service_name=req.service_name,
        )

    @staticmethod
    def request_to_config(req: ReplayRequest) -> ReplayConfig:
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
        )

    @staticmethod
    def op_to_response(session_id: str, status: ReplayStatus, message: str) -> ReplayResponse:
        return ReplayResponse(session_id=session_id, status=status, message=message)

    @staticmethod
    def cleanup_to_response(removed_sessions: int, message: str) -> CleanupResponse:
        return CleanupResponse(removed_sessions=removed_sessions, message=message)
