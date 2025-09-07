from datetime import datetime, timedelta, timezone
from typing import List

from app.core.exceptions import ServiceError
from app.core.logging import logger
from app.db.repositories.replay_repository import ReplayRepository
from app.domain.replay.models import (
    ReplayConfig,
    ReplayFilter,
    ReplayOperationResult,
    ReplaySessionState,
)
from app.schemas_pydantic.replay import CleanupResponse, ReplayRequest, SessionSummary
from app.schemas_pydantic.replay_models import ReplaySession as ReplaySessionSchema
from app.services.event_replay import (
    EventReplayService,
    ReplayStatus,
)


class ReplayService:
    """Service for managing replay sessions and providing business logic"""

    def __init__(
            self,
            repository: ReplayRepository,
            event_replay_service: EventReplayService
    ) -> None:
        self.repository = repository
        self.event_replay_service = event_replay_service

    async def create_session(self, config: ReplayConfig | ReplayRequest) -> ReplayOperationResult:
        """Create a new replay session from domain config"""
        try:
            # Accept either domain ReplayConfig or API ReplayRequest
            if isinstance(config, ReplayRequest):
                cfg = ReplayConfig(
                    replay_type=config.replay_type,
                    target=config.target,
                    filter=ReplayFilter(
                        execution_id=config.execution_id,
                        event_types=config.event_types,
                        start_time=config.start_time.timestamp() if config.start_time else None,
                        end_time=config.end_time.timestamp() if config.end_time else None,
                        user_id=config.user_id,
                        service_name=config.service_name,
                    ),
                    speed_multiplier=config.speed_multiplier,
                    preserve_timestamps=config.preserve_timestamps,
                    batch_size=config.batch_size,
                    max_events=config.max_events,
                    skip_errors=config.skip_errors,
                    target_file_path=config.target_file_path,
                )
            else:
                cfg = config
            session_id = await self.event_replay_service.create_replay_session(cfg)
            session = self.event_replay_service.get_session(session_id)
            if session:
                await self.repository.save_session(session)
            return ReplayOperationResult(
                session_id=session_id,
                status=ReplayStatus.CREATED,
                message="Replay session created successfully",
            )
        except Exception as e:
            logger.error(f"Failed to create replay session: {e}")
            raise ServiceError(str(e), status_code=500) from e

    # create_session_from_config no longer needed; merged into create_session

    async def start_session(self, session_id: str) -> ReplayOperationResult:
        """Start a replay session"""
        logger.info(f"Starting replay session {session_id}")
        try:
            await self.event_replay_service.start_replay(session_id)

            # Update status in database
            await self.repository.update_session_status(session_id, ReplayStatus.RUNNING)

            return ReplayOperationResult(session_id=session_id, status=ReplayStatus.RUNNING,
                                         message="Replay session started")

        except ValueError as e:
            raise ServiceError(str(e), status_code=404) from e
        except Exception as e:
            logger.error(f"Failed to start replay session: {e}")
            raise ServiceError(str(e), status_code=500) from e

    async def pause_session(self, session_id: str) -> ReplayOperationResult:
        """Pause a replay session"""
        try:
            await self.event_replay_service.pause_replay(session_id)

            # Update status in database
            await self.repository.update_session_status(session_id, ReplayStatus.PAUSED)

            return ReplayOperationResult(session_id=session_id, status=ReplayStatus.PAUSED,
                                         message="Replay session paused")

        except ValueError as e:
            raise ServiceError(str(e), status_code=404) from e
        except Exception as e:
            logger.error(f"Failed to pause replay session: {e}")
            raise ServiceError(str(e), status_code=500) from e

    async def resume_session(self, session_id: str) -> ReplayOperationResult:
        """Resume a paused replay session"""
        try:
            await self.event_replay_service.resume_replay(session_id)

            # Update status in database
            await self.repository.update_session_status(session_id, ReplayStatus.RUNNING)

            return ReplayOperationResult(session_id=session_id, status=ReplayStatus.RUNNING,
                                         message="Replay session resumed")

        except ValueError as e:
            raise ServiceError(str(e), status_code=404) from e
        except Exception as e:
            logger.error(f"Failed to resume replay session: {e}")
            raise ServiceError(str(e), status_code=500) from e

    async def cancel_session(self, session_id: str) -> ReplayOperationResult:
        """Cancel a replay session"""
        try:
            await self.event_replay_service.cancel_replay(session_id)

            # Update status in database
            await self.repository.update_session_status(session_id, ReplayStatus.CANCELLED)

            return ReplayOperationResult(session_id=session_id, status=ReplayStatus.CANCELLED,
                                         message="Replay session cancelled")

        except ValueError as e:
            raise ServiceError(str(e), status_code=404) from e
        except Exception as e:
            logger.error(f"Failed to cancel replay session: {e}")
            raise ServiceError(str(e), status_code=500) from e

    def list_sessions(
            self,
            status: ReplayStatus | None = None,
            limit: int = 100
    ) -> List[ReplaySessionState]:
        """List replay sessions with optional filtering (domain objects)."""
        return self.event_replay_service.list_sessions(status=status, limit=limit)

    def get_session(self, session_id: str) -> ReplaySessionState:
        """Get a specific replay session (domain)."""
        try:
            # Get from memory-based service for performance
            session = self.event_replay_service.get_session(session_id)
            if not session:
                raise ServiceError("Session not found", status_code=404)
            return session
        except ServiceError:
            raise
        except Exception as e:
            logger.error(f"Failed to get replay session {session_id}: {e}")
            raise ServiceError("Internal server error", status_code=500) from e

    async def cleanup_old_sessions(self, older_than_hours: int = 24) -> CleanupResponse:
        """Clean up old replay sessions"""
        try:
            # Clean up from memory-based service
            removed_memory = await self.event_replay_service.cleanup_old_sessions(older_than_hours)

            # Clean up from database
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
            removed_db = await self.repository.delete_old_sessions(cutoff_time.isoformat())

            total_removed = max(removed_memory, removed_db)
            return CleanupResponse(removed_sessions=total_removed, message=f"Removed {total_removed} old sessions")
        except Exception as e:
            logger.error(f"Failed to cleanup old sessions: {e}")
            raise ServiceError(str(e), status_code=500) from e

    # Helper used by tests to summarize session info
    def _session_to_summary(self, session: ReplaySessionSchema | ReplaySessionState) -> SessionSummary:
        if isinstance(session, ReplaySessionState):
            # Map domain to schema-like for summary
            created_at = session.created_at
            started_at = session.started_at
            completed_at = session.completed_at
            total = session.total_events
            replayed = session.replayed_events
            failed = session.failed_events
            skipped = session.skipped_events
            rtype = session.config.replay_type
            target = session.config.target
            status = session.status
        else:
            created_at = session.created_at
            started_at = session.started_at
            completed_at = session.completed_at
            total = session.total_events
            replayed = session.replayed_events
            failed = session.failed_events
            skipped = session.skipped_events
            rtype = session.config.replay_type
            target = session.config.target
            status = session.status

        duration_seconds: float | None = None
        throughput: float | None = None
        if started_at and completed_at:
            duration_seconds = max((completed_at - started_at).total_seconds(), 0)
            if duration_seconds > 0 and replayed > 0:
                throughput = replayed / duration_seconds

        return SessionSummary(
            session_id=session.session_id,
            replay_type=rtype,
            target=target,
            status=status,
            total_events=total,
            replayed_events=replayed,
            failed_events=failed,
            skipped_events=skipped,
            created_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
            throughput_events_per_second=throughput,
        )
