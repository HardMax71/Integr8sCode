from datetime import datetime

from fastapi import HTTPException

from app.core.logging import logger
from app.schemas_avro.event_schemas import EventType
from app.schemas_pydantic.replay import CleanupResponse, ReplayResponse, SessionSummary
from app.services.event_replay import (
    EventReplayService,
    ReplayConfig,
    ReplayFilter,
    ReplaySession,
    ReplayStatus,
    ReplayTarget,
    ReplayType,
)


class ReplayRepository:
    """Repository for managing event replay operations"""

    def __init__(self, replay_service: EventReplayService):
        self.replay_service = replay_service

    async def create_session(
            self,
            replay_type: ReplayType,
            target: ReplayTarget,
            execution_id: str | None = None,
            event_types: list[EventType] | None = None,
            start_time: datetime | None = None,
            end_time: datetime | None = None,
            user_id: str | None = None,
            service_name: str | None = None,
            speed_multiplier: float = 1.0,
            preserve_timestamps: bool = False,
            batch_size: int = 100,
            max_events: int | None = None,
            skip_errors: bool = True,
            target_file_path: str | None = None,
            current_user: dict[str, object] | None = None
    ) -> ReplayResponse:
        """Create a new replay session"""
        try:
            replay_filter = ReplayFilter(
                execution_id=execution_id,
                event_types=event_types,
                start_time=start_time,
                end_time=end_time,
                user_id=user_id,
                service_name=service_name
            )

            config = ReplayConfig(
                replay_type=replay_type,
                target=target,
                filter=replay_filter,
                speed_multiplier=speed_multiplier,
                preserve_timestamps=preserve_timestamps,
                batch_size=batch_size,
                max_events=max_events,
                skip_errors=skip_errors,
                target_file_path=target_file_path
            )

            session_id = await self.replay_service.create_replay_session(config)

            if current_user:
                logger.info(
                    f"Created replay session {session_id} for user {current_user.get('id', 'unknown')}"
                )

            return ReplayResponse(
                session_id=session_id,
                status=ReplayStatus.CREATED,
                message="Replay session created successfully"
            )

        except Exception as e:
            logger.error(f"Failed to create replay session: {e}")
            raise HTTPException(status_code=500, detail=str(e)) from e

    async def start_session(self, session_id: str) -> ReplayResponse:
        """Start a replay session"""
        try:
            await self.replay_service.start_replay(session_id)

            return ReplayResponse(
                session_id=session_id,
                status=ReplayStatus.RUNNING,
                message="Replay session started"
            )

        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except Exception as e:
            logger.error(f"Failed to start replay session: {e}")
            raise HTTPException(status_code=500, detail=str(e)) from e

    async def pause_session(self, session_id: str) -> ReplayResponse:
        """Pause a replay session"""
        try:
            await self.replay_service.pause_replay(session_id)

            return ReplayResponse(
                session_id=session_id,
                status=ReplayStatus.PAUSED,
                message="Replay session paused"
            )

        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except Exception as e:
            logger.error(f"Failed to pause replay session: {e}")
            raise HTTPException(status_code=500, detail=str(e)) from e

    async def resume_session(self, session_id: str) -> ReplayResponse:
        """Resume a paused replay session"""
        try:
            await self.replay_service.resume_replay(session_id)

            return ReplayResponse(
                session_id=session_id,
                status=ReplayStatus.RUNNING,
                message="Replay session resumed"
            )

        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except Exception as e:
            logger.error(f"Failed to resume replay session: {e}")
            raise HTTPException(status_code=500, detail=str(e)) from e

    async def cancel_session(self, session_id: str) -> ReplayResponse:
        """Cancel a replay session"""
        try:
            await self.replay_service.cancel_replay(session_id)

            return ReplayResponse(
                session_id=session_id,
                status=ReplayStatus.CANCELLED,
                message="Replay session cancelled"
            )

        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except Exception as e:
            logger.error(f"Failed to cancel replay session: {e}")
            raise HTTPException(status_code=500, detail=str(e)) from e

    def list_sessions(
            self,
            status: ReplayStatus | None = None,
            limit: int = 100
    ) -> list[SessionSummary]:
        """List replay sessions with optional filtering"""
        sessions = self.replay_service.list_sessions(status=status, limit=limit)

        summaries = []
        for session in sessions:
            duration = None
            throughput = None

            if session.started_at and session.completed_at:
                duration = (session.completed_at - session.started_at).total_seconds()
                if session.replayed_events > 0 and duration > 0:
                    throughput = session.replayed_events / duration

            summaries.append(SessionSummary(
                session_id=session.session_id,
                replay_type=session.config.replay_type,
                target=session.config.target,
                status=session.status,
                total_events=session.total_events,
                replayed_events=session.replayed_events,
                failed_events=session.failed_events,
                skipped_events=session.skipped_events,
                created_at=session.created_at,
                started_at=session.started_at,
                completed_at=session.completed_at,
                duration_seconds=duration,
                throughput_events_per_second=throughput
            ))

        return summaries

    def get_session(self, session_id: str) -> ReplaySession:
        """Get a specific replay session"""
        session = self.replay_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session

    async def cleanup_old_sessions(self, older_than_hours: int = 24) -> CleanupResponse:
        """Clean up old replay sessions"""
        removed = await self.replay_service.cleanup_old_sessions(older_than_hours)

        return CleanupResponse(
            removed_sessions=removed,
            message=f"Removed {removed} old sessions"
        )
