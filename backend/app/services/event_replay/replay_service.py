import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import aiofiles
from opentelemetry.trace import SpanKind
from pydantic import ValidationError

from app.core.metrics import ReplayMetrics
from app.core.tracing.utils import trace_span
from app.db.repositories.replay_repository import ReplayRepository
from app.domain.admin.replay_updates import ReplaySessionUpdate
from app.domain.enums.replay import ReplayStatus, ReplayTarget
from app.domain.events.typed import DomainEvent, DomainEventAdapter
from app.domain.replay import (
    CleanupResult,
    ReplayConfig,
    ReplayError,
    ReplayOperationError,
    ReplayOperationResult,
    ReplaySessionNotFoundError,
    ReplaySessionState,
)
from app.events.core import UnifiedProducer


class EventReplayService:
    def __init__(
        self,
        repository: ReplayRepository,
        producer: UnifiedProducer,
        replay_metrics: ReplayMetrics,
        logger: logging.Logger,
    ) -> None:
        self._sessions: dict[str, ReplaySessionState] = {}
        self._active_tasks: dict[str, asyncio.Task[None]] = {}
        self._resume_events: dict[str, asyncio.Event] = {}
        self._repository = repository
        self._producer = producer
        self.logger = logger
        self._file_locks: dict[str, asyncio.Lock] = {}
        self._metrics = replay_metrics

    async def create_session_from_config(self, config: ReplayConfig) -> ReplayOperationResult:
        try:
            state = ReplaySessionState(session_id=str(uuid4()), config=config)
            self._sessions[state.session_id] = state
            await self._repository.save_session(state)
            return ReplayOperationResult(
                session_id=state.session_id,
                status=ReplayStatus.CREATED,
                message="Replay session created successfully",
            )
        except Exception as e:
            self.logger.error(f"Failed to create replay session: {e}")
            raise ReplayOperationError("", "create", str(e)) from e

    async def start_session(self, session_id: str) -> ReplayOperationResult:
        session = self.get_session(session_id)
        if session.status != ReplayStatus.CREATED:
            raise ReplayOperationError(session_id, "start", "Session already started")

        resume_event = asyncio.Event()
        resume_event.set()
        self._resume_events[session_id] = resume_event

        task = asyncio.create_task(self._run_replay(session))
        self._active_tasks[session_id] = task

        session.status = ReplayStatus.RUNNING
        session.started_at = datetime.now(timezone.utc)

        self._metrics.increment_active_replays()
        await self._repository.update_session_status(session_id, ReplayStatus.RUNNING)
        return ReplayOperationResult(
            session_id=session_id, status=ReplayStatus.RUNNING, message="Replay session started"
        )

    async def pause_session(self, session_id: str) -> ReplayOperationResult:
        session = self.get_session(session_id)
        if session.status != ReplayStatus.RUNNING:
            raise ReplayOperationError(session_id, "pause", "Session is not running")
        session.status = ReplayStatus.PAUSED
        resume_event = self._resume_events.get(session_id)
        if resume_event:
            resume_event.clear()
        await self._repository.update_session_status(session_id, ReplayStatus.PAUSED)
        return ReplayOperationResult(
            session_id=session_id, status=ReplayStatus.PAUSED, message="Replay session paused"
        )

    async def resume_session(self, session_id: str) -> ReplayOperationResult:
        session = self.get_session(session_id)
        if session.status != ReplayStatus.PAUSED:
            raise ReplayOperationError(session_id, "resume", "Session is not paused")
        session.status = ReplayStatus.RUNNING
        resume_event = self._resume_events.get(session_id)
        if resume_event:
            resume_event.set()
        await self._repository.update_session_status(session_id, ReplayStatus.RUNNING)
        return ReplayOperationResult(
            session_id=session_id, status=ReplayStatus.RUNNING, message="Replay session resumed"
        )

    async def cancel_session(self, session_id: str) -> ReplayOperationResult:
        session = self.get_session(session_id)
        session.status = ReplayStatus.CANCELLED

        resume_event = self._resume_events.get(session_id)
        if resume_event:
            resume_event.set()

        task = self._active_tasks.get(session_id)
        if task and not task.done():
            task.cancel()

        await self._repository.update_session_status(session_id, ReplayStatus.CANCELLED)
        return ReplayOperationResult(
            session_id=session_id, status=ReplayStatus.CANCELLED, message="Replay session cancelled"
        )

    def get_session(self, session_id: str) -> ReplaySessionState:
        session = self._sessions.get(session_id)
        if not session:
            raise ReplaySessionNotFoundError(session_id)
        return session

    def list_sessions(self, status: ReplayStatus | None = None, limit: int = 100) -> list[ReplaySessionState]:
        sessions = list(self._sessions.values())
        if status:
            sessions = [s for s in sessions if s.status == status]
        sessions.sort(key=lambda s: s.created_at, reverse=True)
        return sessions[:limit]

    async def cleanup_old_sessions(self, older_than_hours: int = 24) -> CleanupResult:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        removed_memory = 0

        completed_statuses = {ReplayStatus.COMPLETED, ReplayStatus.FAILED, ReplayStatus.CANCELLED}
        for session_id in list(self._sessions.keys()):
            session = self._sessions[session_id]
            if session.status in completed_statuses and session.created_at < cutoff_time:
                del self._sessions[session_id]
                removed_memory += 1

        removed_db = await self._repository.delete_old_sessions(cutoff_time)
        total_removed = max(removed_memory, removed_db)

        self.logger.info("Cleaned up old replay sessions", extra={"removed_count": total_removed})
        return CleanupResult(removed_sessions=total_removed, message=f"Removed {total_removed} old sessions")

    async def _run_replay(self, session: ReplaySessionState) -> None:
        try:
            with trace_span(
                name="event_replay.session",
                kind=SpanKind.INTERNAL,
                attributes={
                    "replay.session_id": str(session.session_id),
                    "replay.type": session.config.replay_type,
                    "replay.target": session.config.target,
                },
            ):
                total_count = await self._repository.count_events(session.config.filter)
                session.total_events = min(total_count, session.config.max_events or total_count)

                async for batch in self._fetch_event_batches(session):
                    await self._await_if_paused(session)
                    if session.status != ReplayStatus.RUNNING:
                        return
                    await self._process_batch(session, batch)

                session.status = ReplayStatus.COMPLETED

        except asyncio.CancelledError:
            session.status = ReplayStatus.CANCELLED
        except Exception as e:
            if session.status == ReplayStatus.CANCELLED:
                return
            session.status = ReplayStatus.FAILED
            session.errors.append(
                ReplayError(timestamp=datetime.now(timezone.utc), error=str(e), error_type=type(e).__name__)
            )
            self._metrics.record_replay_error(type(e).__name__)
            self.logger.error(
                "Replay session failed",
                extra={"session_id": session.session_id, "error": str(e)},
                exc_info=True,
            )
        finally:
            session.completed_at = datetime.now(timezone.utc)
            if session.status == ReplayStatus.COMPLETED and session.started_at:
                duration = (session.completed_at - session.started_at).total_seconds()
                self._metrics.record_replay_duration(duration, session.config.replay_type)
            self._metrics.decrement_active_replays()
            await self._update_session_in_db(session)
            self._active_tasks.pop(session.session_id, None)
            self._resume_events.pop(session.session_id, None)
            self.logger.info(
                "Replay session finished",
                extra={
                    "session_id": session.session_id,
                    "status": session.status.value if hasattr(session.status, "value") else session.status,
                    "replayed_events": session.replayed_events,
                    "failed_events": session.failed_events,
                },
            )

    async def _await_if_paused(self, session: ReplaySessionState) -> None:
        if session.status == ReplayStatus.PAUSED:
            resume_event = self._resume_events.get(session.session_id)
            if resume_event:
                await resume_event.wait()

    async def _fetch_event_batches(self, session: ReplaySessionState) -> AsyncIterator[list[DomainEvent]]:
        events_processed = 0
        max_events = session.config.max_events

        async for batch_docs in self._repository.fetch_events(
            replay_filter=session.config.filter, batch_size=session.config.batch_size
        ):
            batch: list[DomainEvent] = []
            for doc in batch_docs:
                if max_events and events_processed >= max_events:
                    break

                try:
                    event = DomainEventAdapter.validate_python(doc)
                except ValidationError as e:
                    session.failed_events += 1
                    self.logger.warning(
                        "Skipping event that failed validation",
                        extra={"event_id": doc.get("event_id", "unknown"), "error": str(e)},
                    )
                    continue

                batch.append(event)
                events_processed += 1

            if batch:
                yield batch

            if max_events and events_processed >= max_events:
                break

    async def _process_batch(self, session: ReplaySessionState, batch: list[DomainEvent]) -> None:
        with trace_span(
            name="event_replay.process_batch",
            kind=SpanKind.INTERNAL,
            attributes={
                "replay.session_id": str(session.session_id),
                "replay.batch.count": len(batch),
                "replay.target": session.config.target,
            },
        ):
            for event in batch:
                await self._await_if_paused(session)
                if session.status != ReplayStatus.RUNNING:
                    return

                if session.last_event_at and session.config.speed_multiplier < 100:
                    time_diff = (event.timestamp - session.last_event_at).total_seconds()
                    delay = time_diff / session.config.speed_multiplier
                    if delay > 0:
                        await asyncio.sleep(delay)

                try:
                    success = await self._replay_event(session, event)
                except Exception as e:
                    self.logger.error("Failed to replay event", extra={"event_id": event.event_id, "error": str(e)})
                    session.failed_events += 1
                    session.errors.append(
                        ReplayError(timestamp=datetime.now(timezone.utc), event_id=str(event.event_id), error=str(e))
                    )
                    if not session.config.skip_errors:
                        raise
                    continue

                if success:
                    session.replayed_events += 1
                else:
                    session.failed_events += 1
                self._metrics.record_event_replayed(
                    session.config.replay_type, event.event_type, "success" if success else "failed"
                )
                session.last_event_at = event.timestamp
                await self._update_session_in_db(session)

    async def _replay_event(self, session: ReplaySessionState, event: DomainEvent) -> bool:
        config = session.config
        attempts = config.retry_attempts if config.retry_failed else 1

        for attempt in range(attempts):
            try:
                match config.target:
                    case ReplayTarget.KAFKA:
                        if not config.preserve_timestamps:
                            event.timestamp = datetime.now(timezone.utc)
                        await self._producer.produce(event_to_produce=event, key=event.aggregate_id or event.event_id)
                    case ReplayTarget.FILE:
                        if not config.target_file_path:
                            self.logger.error("No target file path specified")
                            return False
                        await self._write_event_to_file(event, config.target_file_path)
                    case ReplayTarget.TEST:
                        pass
                    case _:
                        self.logger.error("Unknown replay target", extra={"target": config.target})
                        return False
                return True
            except Exception as e:
                self.logger.error(
                    "Failed to replay event",
                    extra={"attempt": attempt + 1, "max_attempts": attempts, "error": str(e)},
                )
                if attempt < attempts - 1:
                    await asyncio.sleep(min(2**attempt, 10))

        return False

    async def _write_event_to_file(self, event: DomainEvent, file_path: str) -> None:
        if file_path not in self._file_locks:
            self._file_locks[file_path] = asyncio.Lock()

        line = json.dumps(event.model_dump(), default=str) + "\n"
        async with self._file_locks[file_path]:
            async with aiofiles.open(file_path, "a") as f:
                await f.write(line)

    async def _update_session_in_db(self, session: ReplaySessionState) -> None:
        try:
            session_update = ReplaySessionUpdate(
                status=session.status,
                replayed_events=session.replayed_events,
                failed_events=session.failed_events,
                skipped_events=session.skipped_events,
                completed_at=session.completed_at,
            )
            await self._repository.update_replay_session(session_id=session.session_id, updates=session_update)
        except Exception as e:
            self.logger.error(f"Failed to update session in database: {e}")
