import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import aiofiles
import backoff
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pydantic import ValidationError

from app.core.metrics import ReplayMetrics
from app.db.repositories import ReplayRepository
from app.domain.admin import ReplaySessionUpdate
from app.domain.enums import ReplayStatus, ReplayTarget
from app.domain.events import DomainEvent, DomainEventAdapter
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
        logger: structlog.stdlib.BoundLogger,
    ) -> None:
        self._sessions: dict[str, ReplaySessionState] = {}
        self._schedulers: dict[str, AsyncIOScheduler] = {}
        self._batch_iters: dict[str, AsyncIterator[list[DomainEvent]]] = {}
        self._event_buffers: dict[str, list[DomainEvent]] = {}
        self._buffer_indices: dict[str, int] = {}
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
            self._metrics.record_session_created(config.replay_type, config.target)
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

        total_count = await self._repository.count_events(session.config.filter)
        session.total_events = min(total_count, session.config.max_events or total_count)

        batch_iter = self._fetch_event_batches(session)
        self._batch_iters[session_id] = batch_iter

        if not await self._load_next_batch(session_id):
            session.status = ReplayStatus.COMPLETED
            session.completed_at = datetime.now(timezone.utc)
            await self._update_session_in_db(session)
            return ReplayOperationResult(
                session_id=session_id, status=ReplayStatus.COMPLETED, message="No events to replay"
            )

        scheduler = AsyncIOScheduler()
        self._schedulers[session_id] = scheduler
        scheduler.start()
        scheduler.add_job(
            self._dispatch_next,
            trigger="date",
            run_date=datetime.now(timezone.utc),
            args=[session],
            id=f"dispatch_{session_id}",
            misfire_grace_time=None,
        )

        previous_status = session.status
        session.status = ReplayStatus.RUNNING
        session.started_at = datetime.now(timezone.utc)
        self._metrics.increment_active_replays()
        self._metrics.record_status_change(session_id, previous_status, ReplayStatus.RUNNING)
        self._metrics.record_speed_multiplier(session.config.speed_multiplier, session.config.replay_type)
        await self._repository.update_session_status(session_id, ReplayStatus.RUNNING)
        return ReplayOperationResult(
            session_id=session_id, status=ReplayStatus.RUNNING, message="Replay session started"
        )

    async def pause_session(self, session_id: str) -> ReplayOperationResult:
        session = self.get_session(session_id)
        if session.status != ReplayStatus.RUNNING:
            raise ReplayOperationError(session_id, "pause", "Session is not running")
        previous_status = session.status
        session.status = ReplayStatus.PAUSED
        self._metrics.record_status_change(session_id, previous_status, ReplayStatus.PAUSED)
        scheduler = self._schedulers.get(session_id)
        if scheduler:
            scheduler.remove_all_jobs()
        await self._repository.update_session_status(session_id, ReplayStatus.PAUSED)
        return ReplayOperationResult(
            session_id=session_id, status=ReplayStatus.PAUSED, message="Replay session paused"
        )

    async def resume_session(self, session_id: str) -> ReplayOperationResult:
        session = self.get_session(session_id)
        if session.status != ReplayStatus.PAUSED:
            raise ReplayOperationError(session_id, "resume", "Session is not paused")
        previous_status = session.status
        session.status = ReplayStatus.RUNNING
        self._metrics.record_status_change(session_id, previous_status, ReplayStatus.RUNNING)
        scheduler = self._schedulers.get(session_id)
        if scheduler:
            scheduler.add_job(
                self._dispatch_next,
                trigger="date",
                run_date=datetime.now(timezone.utc),
                args=[session],
                id=f"dispatch_{session_id}",
                replace_existing=True,
                misfire_grace_time=None,
            )
        await self._repository.update_session_status(session_id, ReplayStatus.RUNNING)
        return ReplayOperationResult(
            session_id=session_id, status=ReplayStatus.RUNNING, message="Replay session resumed"
        )

    async def cancel_session(self, session_id: str) -> ReplayOperationResult:
        session = self.get_session(session_id)
        await self._finalize_session(session, ReplayStatus.CANCELLED)
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

        self.logger.info("Cleaned up old replay sessions", removed_count=total_removed)
        return CleanupResult(removed_sessions=total_removed, message=f"Removed {total_removed} old sessions")

    async def _dispatch_next(self, session: ReplaySessionState) -> None:
        if session.status != ReplayStatus.RUNNING:
            return

        event = self._pop_next_event(session.session_id)
        if event is None:
            if not await self._load_next_batch(session.session_id):
                await self._finalize_session(session, ReplayStatus.COMPLETED)
                return
            event = self._pop_next_event(session.session_id)
            if event is None:
                await self._finalize_session(session, ReplayStatus.COMPLETED)
                return

        buf = self._event_buffers.get(session.session_id, [])
        idx = self._buffer_indices.get(session.session_id, 0)
        self._metrics.update_replay_queue_size(session.session_id, len(buf) - idx)

        success = False
        t0 = time.monotonic()
        try:
            success = await self._replay_event(session, event)
        except Exception as e:
            processing_time = time.monotonic() - t0
            self._metrics.record_event_processing_time(processing_time, event.event_type)
            session.errors.append(
                ReplayError(timestamp=datetime.now(timezone.utc), event_id=str(event.event_id), error=str(e))
            )
            if not session.config.skip_errors:
                session.failed_events += 1
                await self._finalize_session(session, ReplayStatus.FAILED)
                return
        else:
            processing_time = time.monotonic() - t0
            self._metrics.record_event_processing_time(processing_time, event.event_type)

        if success:
            session.replayed_events += 1
        else:
            session.failed_events += 1
        self._metrics.record_event_replayed(
            session.config.replay_type, event.event_type, "success" if success else "failed"
        )
        session.last_event_at = event.timestamp
        await self._update_session_in_db(session)

        next_event = self._peek_next_event(session.session_id)
        delay = 0.0
        if next_event and session.last_event_at and session.config.speed_multiplier < 100:
            time_diff = (next_event.timestamp - session.last_event_at).total_seconds()
            delay = max(time_diff / session.config.speed_multiplier, 0)

        if delay > 0:
            self._metrics.record_delay_applied(delay)

        scheduler = self._schedulers.get(session.session_id)
        if scheduler and scheduler.running and session.status == ReplayStatus.RUNNING:
            scheduler.add_job(
                self._dispatch_next,
                trigger="date",
                run_date=datetime.now(timezone.utc) + timedelta(seconds=delay),
                args=[session],
                id=f"dispatch_{session.session_id}",
                replace_existing=True,
                misfire_grace_time=None,
            )

    def _pop_next_event(self, session_id: str) -> DomainEvent | None:
        idx = self._buffer_indices.get(session_id, 0)
        buf = self._event_buffers.get(session_id, [])
        if idx < len(buf):
            self._buffer_indices[session_id] = idx + 1
            return buf[idx]
        return None

    def _peek_next_event(self, session_id: str) -> DomainEvent | None:
        idx = self._buffer_indices.get(session_id, 0)
        buf = self._event_buffers.get(session_id, [])
        if idx < len(buf):
            return buf[idx]
        return None

    async def _load_next_batch(self, session_id: str) -> bool:
        batch_iter = self._batch_iters.get(session_id)
        if not batch_iter:
            return False
        try:
            batch = await batch_iter.__anext__()
            self._event_buffers[session_id] = batch
            self._buffer_indices[session_id] = 0
            session = self._sessions.get(session_id)
            if session:
                self._metrics.record_batch_size(len(batch), session.config.replay_type)
            self._metrics.update_replay_queue_size(session_id, len(batch))
            return True
        except StopAsyncIteration:
            return False

    async def _finalize_session(self, session: ReplaySessionState, final_status: ReplayStatus) -> None:
        previous_status = session.status
        session.status = final_status
        session.completed_at = datetime.now(timezone.utc)
        if final_status == ReplayStatus.COMPLETED and session.started_at:
            duration = (session.completed_at - session.started_at).total_seconds()
            total_events = session.replayed_events + session.failed_events
            self._metrics.record_replay_duration(duration, session.config.replay_type, total_events=total_events)
        self._metrics.record_status_change(session.session_id, previous_status, final_status)
        self._metrics.decrement_active_replays()
        self._metrics.update_replay_queue_size(session.session_id, 0)
        await self._update_session_in_db(session)
        scheduler = self._schedulers.pop(session.session_id, None)
        if scheduler:
            scheduler.shutdown(wait=False)
        self._batch_iters.pop(session.session_id, None)
        self._event_buffers.pop(session.session_id, None)
        self._buffer_indices.pop(session.session_id, None)
        self.logger.info(
            "Replay session finished",
            session_id=session.session_id,
            status=session.status,
            replayed_events=session.replayed_events,
            failed_events=session.failed_events,
        )

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
                        event_id=doc.get("event_id", "unknown"),
                        error=str(e),
                    )
                    continue

                batch.append(event)
                events_processed += 1

            if batch:
                yield batch

            if max_events and events_processed >= max_events:
                break

    async def _replay_event(self, session: ReplaySessionState, event: DomainEvent) -> bool:
        config = session.config
        if config.target == ReplayTarget.FILE and not config.target_file_path:
            self.logger.error("No target file path specified")
            return False

        max_attempts = config.retry_attempts if config.retry_failed else 1

        @backoff.on_exception(
            backoff.expo,
            Exception,
            max_tries=max_attempts,
            max_value=10,
            jitter=None,
            on_backoff=lambda details: self.logger.error(
                "Failed to replay event",
                attempt=details["tries"],
                max_attempts=max_attempts,
                error=str(details["exception"]),
            ),
        )
        async def _dispatch() -> None:
            match config.target:
                case ReplayTarget.KAFKA:
                    if not config.preserve_timestamps:
                        event.timestamp = datetime.now(timezone.utc)
                    await self._producer.produce(event_to_produce=event, key=event.aggregate_id or event.event_id)
                case ReplayTarget.FILE:
                    await self._write_event_to_file(event, config.target_file_path)  # type: ignore[arg-type]
                case ReplayTarget.TEST:
                    pass
                case _:
                    raise ValueError(f"Unknown replay target: {config.target}")

        try:
            await _dispatch()
            self._metrics.record_replay_by_target(config.target, success=True)
            return True
        except Exception:
            self._metrics.record_replay_by_target(config.target, success=False)
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
