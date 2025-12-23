from datetime import datetime, timedelta, timezone
from typing import List

from app.core.exceptions import ServiceError
from app.core.logging import logger
from app.db.repositories.replay_repository import ReplayRepository
from app.domain.replay import (
    ReplayConfig,
    ReplayOperationResult,
    ReplaySessionState,
)
from app.schemas_pydantic.replay import CleanupResponse
from app.services.event_replay import (
    EventReplayService,
    ReplayStatus,
)


class ReplayService:
    """Service for managing replay sessions and providing business logic"""

    def __init__(self, repository: ReplayRepository, event_replay_service: EventReplayService) -> None:
        self.repository = repository
        self.event_replay_service = event_replay_service

    async def create_session_from_config(self, config: ReplayConfig) -> ReplayOperationResult:
        """Create a new replay session from a domain config"""
        try:
            session_id = await self.event_replay_service.create_replay_session(config)
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

    async def start_session(self, session_id: str) -> ReplayOperationResult:
        """Start a replay session"""
        logger.info(f"Starting replay session {session_id}")
        try:
            await self.event_replay_service.start_replay(session_id)

            await self.repository.update_session_status(session_id, ReplayStatus.RUNNING)

            return ReplayOperationResult(
                session_id=session_id, status=ReplayStatus.RUNNING, message="Replay session started"
            )

        except ValueError as e:
            raise ServiceError(str(e), status_code=404) from e
        except Exception as e:
            logger.error(f"Failed to start replay session: {e}")
            raise ServiceError(str(e), status_code=500) from e

    async def pause_session(self, session_id: str) -> ReplayOperationResult:
        """Pause a replay session"""
        try:
            await self.event_replay_service.pause_replay(session_id)

            await self.repository.update_session_status(session_id, ReplayStatus.PAUSED)

            return ReplayOperationResult(
                session_id=session_id, status=ReplayStatus.PAUSED, message="Replay session paused"
            )

        except ValueError as e:
            raise ServiceError(str(e), status_code=404) from e
        except Exception as e:
            logger.error(f"Failed to pause replay session: {e}")
            raise ServiceError(str(e), status_code=500) from e

    async def resume_session(self, session_id: str) -> ReplayOperationResult:
        """Resume a paused replay session"""
        try:
            await self.event_replay_service.resume_replay(session_id)

            await self.repository.update_session_status(session_id, ReplayStatus.RUNNING)

            return ReplayOperationResult(
                session_id=session_id, status=ReplayStatus.RUNNING, message="Replay session resumed"
            )

        except ValueError as e:
            raise ServiceError(str(e), status_code=404) from e
        except Exception as e:
            logger.error(f"Failed to resume replay session: {e}")
            raise ServiceError(str(e), status_code=500) from e

    async def cancel_session(self, session_id: str) -> ReplayOperationResult:
        """Cancel a replay session"""
        try:
            await self.event_replay_service.cancel_replay(session_id)

            await self.repository.update_session_status(session_id, ReplayStatus.CANCELLED)

            return ReplayOperationResult(
                session_id=session_id, status=ReplayStatus.CANCELLED, message="Replay session cancelled"
            )

        except ValueError as e:
            raise ServiceError(str(e), status_code=404) from e
        except Exception as e:
            logger.error(f"Failed to cancel replay session: {e}")
            raise ServiceError(str(e), status_code=500) from e

    def list_sessions(self, status: ReplayStatus | None = None, limit: int = 100) -> List[ReplaySessionState]:
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
            removed_memory = await self.event_replay_service.cleanup_old_sessions(older_than_hours)

            # Clean up from database
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
            removed_db = await self.repository.delete_old_sessions(cutoff_time.isoformat())

            total_removed = max(removed_memory, removed_db)
            return CleanupResponse(removed_sessions=total_removed, message=f"Removed {total_removed} old sessions")
        except Exception as e:
            logger.error(f"Failed to cleanup old sessions: {e}")
            raise ServiceError(str(e), status_code=500) from e
