import asyncio
import json
import time
from collections import Counter
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import aiofiles
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from opentelemetry import trace
from opentelemetry.util.types import AttributeValue
from pydantic import ValidationError
from pymongo.errors import PyMongoError
from redis.exceptions import RedisError
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.db import ReplayRepository
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
from app.domain.sse import DomainReplaySSEPayload
from app.events import PRODUCE_ERRORS, UnifiedProducer
from app.services.sse.redis_bus import SSERedisBus

_DISPATCH_ERRORS: tuple[type[Exception], ...] = (*PRODUCE_ERRORS, OSError, ValueError)


class EventReplayService:
    def __init__(
        self,
        repository: ReplayRepository,
        producer: UnifiedProducer,
        tracer: trace.Tracer,
        logger: structlog.stdlib.BoundLogger,
        sse_bus: SSERedisBus,
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
        self._tracer = tracer
        self._sse_bus = sse_bus

    async def create_session_from_config(self, config: ReplayConfig) -> ReplayOperationResult:
        try:
            state = ReplaySessionState(session_id=str(uuid4()), config=config)
            self._sessions[state.session_id] = state
            await self._repository.save_session(state)
            attributes = {"replay.type": config.replay_type, "replay.target": config.target}
            self._tracer.start_span("replay.session_created", attributes=attributes).end()
            return ReplayOperationResult(
                session_id=state.session_id,
                status=ReplayStatus.CREATED,
                message="Replay session created successfully",
            )
        except (PyMongoError, ValidationError) as e:
            self.logger.error("Failed to create replay session", error=str(e))
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
            self._report_status_change(ReplayStatus.CREATED, ReplayStatus.COMPLETED)
            await self._update_session_in_db(session)
            return ReplayOperationResult(
                session_id=session_id, status=ReplayStatus.COMPLETED, message="No events to replay"
            )

        scheduler = AsyncIOScheduler()
        self._schedulers[session_id] = scheduler
        scheduler.start()
        scheduler.add_job(
            self._dispatch_events,
            trigger="date",
            run_date=datetime.now(timezone.utc),
            args=[session],
            id=f"dispatch_{session_id}",
            misfire_grace_time=None,
        )

        previous_status = session.status
        session.status = ReplayStatus.RUNNING
        session.started_at = datetime.now(timezone.utc)
        self._report_status_change(previous_status, ReplayStatus.RUNNING)
        attributes: dict[str, AttributeValue] = {
            "replay.type": session.config.replay_type,
            "replay.speed_multiplier": session.config.speed_multiplier,
        }
        self._tracer.start_span("replay.session_started", attributes=attributes).end()
        await self._repository.update_session_status(session_id, ReplayStatus.RUNNING)
        await self._publish_replay_status(session)
        return ReplayOperationResult(
            session_id=session_id, status=ReplayStatus.RUNNING, message="Replay session started"
        )

    async def pause_session(self, session_id: str) -> ReplayOperationResult:
        session = self.get_session(session_id)
        if session.status != ReplayStatus.RUNNING:
            raise ReplayOperationError(session_id, "pause", "Session is not running")
        previous_status = session.status
        session.status = ReplayStatus.PAUSED
        self._report_status_change(previous_status, ReplayStatus.PAUSED)
        scheduler = self._schedulers.get(session_id)
        if scheduler:
            scheduler.remove_all_jobs()
        await self._repository.update_session_status(session_id, ReplayStatus.PAUSED)
        return ReplayOperationResult(session_id=session_id, status=ReplayStatus.PAUSED, message="Replay session paused")

    async def resume_session(self, session_id: str) -> ReplayOperationResult:
        session = self.get_session(session_id)
        if session.status != ReplayStatus.PAUSED:
            raise ReplayOperationError(session_id, "resume", "Session is not paused")
        previous_status = session.status
        session.status = ReplayStatus.RUNNING
        self._report_status_change(previous_status, ReplayStatus.RUNNING)
        scheduler = self._schedulers.get(session_id)
        if scheduler:
            scheduler.add_job(
                self._dispatch_events,
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

        for session_id in list(self._sessions.keys()):
            session = self._sessions[session_id]
            if session.status.is_terminal and session.created_at < cutoff_time:
                del self._sessions[session_id]
                removed_memory += 1

        removed_db = await self._repository.delete_old_sessions(cutoff_time)
        total_removed = max(removed_memory, removed_db)

        self.logger.info("Cleaned up old replay sessions", removed_count=total_removed)
        return CleanupResult(removed_sessions=total_removed, message=f"Removed {total_removed} old sessions")

    async def report_sessions(self) -> None:
        """Report the sessions per status and the loaded events still to send, for the collector's gauges."""
        with self._tracer.start_as_current_span("replay.report") as span:
            queued = sum(len(buf) - self._buffer_indices.get(sid, 0) for sid, buf in self._event_buffers.items())
            span.set_attribute("replay.queued_events", queued)
            counts = Counter(session.status for session in self._sessions.values())
            for status in ReplayStatus:
                attributes: dict[str, AttributeValue] = {"replay.status": status, "replay.sessions": counts[status]}
                self._tracer.start_span("replay.sessions", attributes=attributes).end()

    def _report_status_change(self, from_status: ReplayStatus, to_status: ReplayStatus) -> None:
        attributes = {"replay.from_status": from_status, "replay.to_status": to_status}
        self._tracer.start_span("replay.status_change", attributes=attributes).end()

    def _report_event(
        self, session: ReplaySessionState, event: DomainEvent, replayed: bool, seconds: float, delay: float
    ) -> None:
        attributes: dict[str, AttributeValue] = {
            "replay.type": session.config.replay_type,
            "replay.event_type": event.event_type,
            "replay.result": "replayed" if replayed else "failed",
            "replay.processing_seconds": seconds,
        }
        if delay > 0:
            attributes["replay.delay_seconds"] = delay
        self._tracer.start_span("replay.event", attributes=attributes).end()

    async def _dispatch_events(self, session: ReplaySessionState) -> None:
        """Replay the session's events in order, waiting out each delay, until it stops running or runs out.

        One job runs the whole loop, since APScheduler skips a run of a job whose previous run hasn't returned.
        """
        while session.status == ReplayStatus.RUNNING:
            event = await self._next_event(session.session_id)
            if event is None:
                await self._finalize_session(session, ReplayStatus.COMPLETED)
                return
            await asyncio.sleep(await self._dispatch_event(session, event))

    async def _next_event(self, session_id: str) -> DomainEvent | None:
        """The session's next event, loading the next batch once the loaded one runs out."""
        event = self._pop_next_event(session_id)
        if event is None and await self._load_next_batch(session_id):
            event = self._pop_next_event(session_id)
        return event

    async def _dispatch_event(self, session: ReplaySessionState, event: DomainEvent) -> float:
        """Replay one event and return the wait before the next; a failure without skip_errors ends the session."""
        success = False
        t0 = time.monotonic()
        try:
            success = await self._replay_event(session, event)
        except Exception as e:
            processing_time = time.monotonic() - t0
            session.errors.append(
                ReplayError(timestamp=datetime.now(timezone.utc), event_id=str(event.event_id), error=str(e))
            )
            if not session.config.skip_errors:
                session.failed_events += 1
                self._report_event(session, event, False, processing_time, 0.0)
                await self._finalize_session(session, ReplayStatus.FAILED)
                return 0.0
        else:
            processing_time = time.monotonic() - t0

        if success:
            session.replayed_events += 1
        else:
            session.failed_events += 1
        session.last_event_at = event.timestamp
        await self._update_session_in_db(session)

        next_event = self._peek_next_event(session.session_id)
        delay = 0.0
        if next_event and session.last_event_at and session.config.speed_multiplier < 100:
            time_diff = (next_event.timestamp - session.last_event_at).total_seconds()
            delay = max(time_diff / session.config.speed_multiplier, 0)

        self._report_event(session, event, success, processing_time, delay)
        return delay

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
                attributes: dict[str, AttributeValue] = {
                    "replay.type": session.config.replay_type,
                    "replay.batch_size": len(batch),
                }
                self._tracer.start_span("replay.batch", attributes=attributes).end()
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
            attributes: dict[str, AttributeValue] = {
                "replay.type": session.config.replay_type,
                "replay.duration_seconds": duration,
            }
            if total_events > 0 and duration > 0:
                attributes["replay.throughput"] = total_events / duration
            self._tracer.start_span("replay.session_completed", attributes=attributes).end()
        self._report_status_change(previous_status, final_status)
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

        retrying = AsyncRetrying(
            retry=retry_if_exception_type(_DISPATCH_ERRORS),
            stop=stop_after_attempt(config.retry_attempts if config.retry_failed else 1),
            wait=wait_exponential(max=10),
            before_sleep=self._log_replay_retry,
            reraise=True,
        )

        success = False
        try:
            await retrying(self._dispatch, event, config)
            success = True
        except _DISPATCH_ERRORS:
            return False
        finally:
            # Unexpected errors still propagate to _dispatch_events, but count against the target first
            attributes: dict[str, AttributeValue] = {"replay.target": config.target, "replay.target_success": success}
            self._tracer.start_span("replay.target", attributes=attributes).end()
        return True

    def _log_replay_retry(self, state: RetryCallState) -> None:
        """Log a failed replay attempt; the retried call's arguments are the event and the session's config."""
        config: ReplayConfig = state.args[1]
        self.logger.error(
            "Failed to replay event",
            attempt=state.attempt_number,
            max_attempts=config.retry_attempts if config.retry_failed else 1,
            error=str(state.outcome.exception() if state.outcome else None),
        )

    async def _dispatch(self, event: DomainEvent, config: ReplayConfig) -> None:
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
        except PyMongoError as e:
            self.logger.error("Failed to update session in database", session_id=session.session_id, error=str(e))
        await self._publish_replay_status(session)

    async def _publish_replay_status(self, session: ReplaySessionState) -> None:
        try:
            payload = DomainReplaySSEPayload(
                session_id=session.session_id,
                status=session.status,
                total_events=session.total_events,
                replayed_events=session.replayed_events,
                failed_events=session.failed_events,
                skipped_events=session.skipped_events,
                replay_id=session.replay_id,
                created_at=session.created_at,
                started_at=session.started_at,
                completed_at=session.completed_at,
                errors=session.errors,
            )
            await self._sse_bus.publish_replay_status(session.session_id, payload)
        except RedisError as e:
            self.logger.error("Failed to publish replay status to SSE", error=str(e))
