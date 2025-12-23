import asyncio
import inspect
import json
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Callable, Dict, List
from uuid import uuid4

from opentelemetry.trace import SpanKind

from app.core.logging import logger
from app.core.metrics import ReplayMetrics
from app.core.tracing.utils import trace_span
from app.db.repositories.replay_repository import ReplayRepository
from app.domain.admin.replay_updates import ReplaySessionUpdate
from app.domain.enums.replay import ReplayStatus, ReplayTarget
from app.domain.replay import ReplayConfig, ReplaySessionState
from app.events.core import UnifiedProducer
from app.events.event_store import EventStore
from app.infrastructure.kafka.events.base import BaseEvent


class EventReplayService:
    def __init__(
        self,
        repository: ReplayRepository,
        producer: UnifiedProducer,
        event_store: EventStore,
    ) -> None:
        self._sessions: Dict[str, ReplaySessionState] = {}
        self._active_tasks: Dict[str, asyncio.Task[None]] = {}
        self._repository = repository
        self._producer = producer
        self._event_store = event_store
        self._callbacks: Dict[ReplayTarget, Callable[..., Any]] = {}
        self._file_locks: Dict[str, asyncio.Lock] = {}
        self._metrics = ReplayMetrics()
        logger.info("Event replay service initialized")

    async def create_replay_session(self, config: ReplayConfig) -> str:
        state = ReplaySessionState(session_id=str(uuid4()), config=config)
        self._sessions[state.session_id] = state

        logger.info(f"Created replay session {state.session_id} type={config.replay_type} target={config.target}")

        return state.session_id

    async def start_replay(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        if session.status != ReplayStatus.CREATED:
            raise ValueError(f"Session {session_id} already started")

        task = asyncio.create_task(self._run_replay(session))
        self._active_tasks[session_id] = task

        session.status = ReplayStatus.RUNNING
        session.started_at = datetime.now(timezone.utc)

        self._metrics.increment_active_replays()
        logger.info(f"Started replay session {session_id}")

    async def _run_replay(self, session: ReplaySessionState) -> None:
        start_time = asyncio.get_event_loop().time()

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
                await self._prepare_session(session)

                async for batch in self._fetch_event_batches(session):
                    if session.status != ReplayStatus.RUNNING:
                        break

                    await self._process_batch(session, batch)
                    await self._handle_progress_callback(session)

                await self._complete_session(session, start_time)

        except Exception as e:
            await self._handle_session_error(session, e)
        finally:
            self._metrics.decrement_active_replays()
            self._active_tasks.pop(session.session_id, None)

    async def _prepare_session(self, session: ReplaySessionState) -> None:
        total_count = await self._repository.count_events(session.config.filter)
        session.total_events = min(total_count, session.config.max_events or total_count)

        logger.info(f"Replay session {session.session_id} will process {session.total_events} events")

    async def _handle_progress_callback(self, session: ReplaySessionState) -> None:
        cb = session.config.get_progress_callback()
        if cb is not None:
            try:
                result = cb(session)
                if inspect.isawaitable(result):
                    await result
            except Exception as e:
                logger.error(f"Progress callback error: {e}")

    async def _complete_session(self, session: ReplaySessionState, start_time: float) -> None:
        session.status = ReplayStatus.COMPLETED
        session.completed_at = datetime.now(timezone.utc)

        duration = asyncio.get_event_loop().time() - start_time
        self._metrics.record_replay_duration(duration, session.config.replay_type)

        await self._update_session_in_db(session)

        logger.info(
            f"Replay session {session.session_id} completed. "
            f"Replayed: {session.replayed_events}, "
            f"Failed: {session.failed_events}, "
            f"Skipped: {session.skipped_events}, "
            f"Duration: {duration:.2f}s"
        )

    async def _handle_session_error(self, session: ReplaySessionState, error: Exception) -> None:
        logger.error(f"Replay session {session.session_id} failed: {error}", exc_info=True)
        session.status = ReplayStatus.FAILED
        session.completed_at = datetime.now(timezone.utc)
        session.errors.append(
            {"timestamp": datetime.now(timezone.utc).isoformat(), "error": str(error), "type": type(error).__name__}
        )
        self._metrics.record_replay_error(type(error).__name__)
        await self._update_session_in_db(session)

    async def _apply_replay_delay(self, session: ReplaySessionState, event: BaseEvent) -> None:
        if session.last_event_at and session.config.speed_multiplier < 100:
            time_diff = (event.timestamp - session.last_event_at).total_seconds()
            delay = time_diff / session.config.speed_multiplier
            if delay > 0:
                await asyncio.sleep(delay)

    def _update_replay_metrics(self, session: ReplaySessionState, event: BaseEvent, success: bool) -> None:
        if success:
            session.replayed_events += 1
            status = "success"
        else:
            session.failed_events += 1
            status = "failed"

        self._metrics.record_event_replayed(session.config.replay_type, event.event_type, status)

    async def _handle_replay_error(self, session: ReplaySessionState, event: BaseEvent, error: Exception) -> None:
        logger.error(f"Failed to replay event {event.event_id}: {error}")
        session.failed_events += 1
        session.errors.append(
            {"timestamp": datetime.now(timezone.utc).isoformat(), "event_id": str(event.event_id), "error": str(error)}
        )

    async def _replay_to_kafka(self, session: ReplaySessionState, event: BaseEvent) -> bool:
        config = session.config
        if not config.preserve_timestamps:
            event.timestamp = datetime.now(timezone.utc)

        # Send the event without modifying its metadata structure
        await self._producer.produce(event_to_produce=event)
        return True

    async def _replay_to_callback(self, event: BaseEvent, session: ReplaySessionState) -> bool:
        callback = self._callbacks.get(ReplayTarget.CALLBACK)
        if callback:
            await callback(event, session)
            return True
        return False

    async def _replay_to_file(self, event: BaseEvent, file_path: str | None) -> bool:
        if not file_path:
            logger.error("No target file path specified")
            return False
        await self._write_event_to_file(event, file_path)
        return True

    async def _fetch_event_batches(self, session: ReplaySessionState) -> AsyncIterator[List[BaseEvent]]:
        logger.info(f"Fetching events for session {session.session_id}")
        events_processed = 0
        max_events = session.config.max_events

        async for batch_docs in self._repository.fetch_events(
            filter=session.config.filter, batch_size=session.config.batch_size
        ):
            batch: List[BaseEvent] = []
            for doc in batch_docs:
                if max_events and events_processed >= max_events:
                    break

                event = self._event_store.schema_registry.deserialize_json(doc)
                if event:
                    batch.append(event)
                    events_processed += 1

            if batch:
                yield batch

            if max_events and events_processed >= max_events:
                break

    async def _process_batch(self, session: ReplaySessionState, batch: List[BaseEvent]) -> None:
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
                if session.status != ReplayStatus.RUNNING:
                    break

                # Apply delay before external I/O
                await self._apply_replay_delay(session, event)
                try:
                    success = await self._replay_event(session, event)
                except Exception as e:
                    await self._handle_replay_error(session, event, e)
                    if not session.config.skip_errors:
                        raise
                    continue

                self._update_replay_metrics(session, event, success)
                session.last_event_at = event.timestamp
                await self._update_session_in_db(session)

    async def _replay_event(self, session: ReplaySessionState, event: BaseEvent) -> bool:
        config = session.config

        attempts = config.retry_attempts if config.retry_failed else 1
        for attempt in range(attempts):
            try:
                if config.target == ReplayTarget.KAFKA:
                    return await self._replay_to_kafka(session, event)
                elif config.target == ReplayTarget.CALLBACK:
                    return await self._replay_to_callback(event, session)
                elif config.target == ReplayTarget.FILE:
                    return await self._replay_to_file(event, config.target_file_path)
                elif config.target == ReplayTarget.TEST:
                    return True
                else:
                    logger.error(f"Unknown replay target: {config.target}")
                    return False
            except Exception as e:
                logger.error(f"Failed to replay event (attempt {attempt + 1}/{attempts}): {e}")
                if attempt < attempts - 1:
                    await asyncio.sleep(min(2**attempt, 10))
                    continue

        return False

    async def _write_event_to_file(self, event: BaseEvent, file_path: str) -> None:
        if file_path not in self._file_locks:
            self._file_locks[file_path] = asyncio.Lock()

        async with self._file_locks[file_path]:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._write_to_file_sync, event, file_path)

    def _write_to_file_sync(self, event: BaseEvent, file_path: str) -> None:
        with open(file_path, "a") as f:
            f.write(json.dumps(event.model_dump(), default=str) + "\n")

    async def pause_replay(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        if session.status == ReplayStatus.RUNNING:
            session.status = ReplayStatus.PAUSED
            logger.info(f"Paused replay session {session_id}")

    async def resume_replay(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        if session.status == ReplayStatus.PAUSED:
            session.status = ReplayStatus.RUNNING
            logger.info(f"Resumed replay session {session_id}")

    async def cancel_replay(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        session.status = ReplayStatus.CANCELLED

        task = self._active_tasks.get(session_id)
        if task and not task.done():
            task.cancel()

        logger.info(f"Cancelled replay session {session_id}")

    def get_session(self, session_id: str) -> ReplaySessionState | None:
        return self._sessions.get(session_id)

    def list_sessions(self, status: ReplayStatus | None = None, limit: int = 100) -> List[ReplaySessionState]:
        sessions = list(self._sessions.values())

        if status:
            sessions = [s for s in sessions if s.status == status]

        sessions.sort(key=lambda s: s.created_at, reverse=True)
        return sessions[:limit]

    def register_callback(self, target: ReplayTarget, callback: Callable[[BaseEvent, ReplaySessionState], Any]) -> None:
        self._callbacks[target] = callback

    async def cleanup_old_sessions(self, older_than_hours: int = 24) -> int:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        removed = 0

        completed_statuses = {ReplayStatus.COMPLETED, ReplayStatus.FAILED, ReplayStatus.CANCELLED}

        for session_id in list(self._sessions.keys()):
            session = self._sessions[session_id]
            if session.status in completed_statuses and session.created_at < cutoff_time:
                del self._sessions[session_id]
                removed += 1

        logger.info(f"Cleaned up {removed} old replay sessions")
        return removed

    async def _update_session_in_db(self, session: ReplaySessionState) -> None:
        """Update session progress in the database."""
        try:
            session_update = ReplaySessionUpdate(
                status=session.status,
                replayed_events=session.replayed_events,
                failed_events=session.failed_events,
                skipped_events=session.skipped_events,
                completed_at=session.completed_at,
            )
            # Note: last_event_at is not in ReplaySessionUpdate
            # If needed, add it to the domain model
            await self._repository.update_replay_session(session_id=session.session_id, updates=session_update)
        except Exception as e:
            logger.error(f"Failed to update session in database: {e}")
