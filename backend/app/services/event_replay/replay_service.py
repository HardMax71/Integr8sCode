import asyncio
import json
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, AsyncIterator, Callable, ClassVar, Dict, List, Optional, Type
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from app.core.logging import logger
from app.core.tracing import SpanKind, trace_span
from app.events.core.producer import UnifiedProducer
from app.events.store.event_store import EventStore
from app.schemas_avro.event_schemas import BaseEvent, EventType, build_event_type_mapping
from app.services.event_replay.metrics import (
    ACTIVE_REPLAYS,
    EVENTS_REPLAYED,
    REPLAY_DURATION,
    REPLAY_ERRORS,
)


class ReplayType(StrEnum):
    EXECUTION = "execution"
    TIME_RANGE = "time_range"
    EVENT_TYPE = "event_type"
    QUERY = "query"
    RECOVERY = "recovery"


class ReplayStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReplayTarget(StrEnum):
    KAFKA = "kafka"
    CALLBACK = "callback"
    FILE = "file"
    TEST = "test"


class ReplayFilter(BaseModel):
    execution_id: Optional[str] = None
    event_types: Optional[List[EventType]] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    user_id: Optional[str] = None
    service_name: Optional[str] = None
    custom_query: Optional[Dict[str, Any]] = None
    exclude_event_types: Optional[List[EventType]] = None

    def to_mongo_query(self) -> Dict[str, Any]:
        query: Dict[str, Any] = {}

        if self.execution_id:
            query["execution_id"] = str(self.execution_id)

        if self.event_types:
            query["event_type"] = {"$in": [str(et) for et in self.event_types]}

        if self.exclude_event_types:
            if "event_type" in query:
                query["event_type"]["$nin"] = [str(et) for et in self.exclude_event_types]
            else:
                query["event_type"] = {"$nin": [str(et) for et in self.exclude_event_types]}

        if self.start_time or self.end_time:
            time_query: Dict[str, Any] = {}
            if self.start_time:
                time_query["$gte"] = self.start_time
            if self.end_time:
                time_query["$lte"] = self.end_time
            query["timestamp"] = time_query

        if self.user_id:
            query["metadata.user_id"] = self.user_id

        if self.service_name:
            query["metadata.service_name"] = self.service_name

        if self.custom_query:
            query.update(self.custom_query)

        return query


class ReplayConfig(BaseModel):
    replay_type: ReplayType
    target: ReplayTarget = ReplayTarget.KAFKA
    filter: ReplayFilter

    speed_multiplier: float = Field(default=1.0, ge=0.1, le=100.0)
    preserve_timestamps: bool = False
    batch_size: int = Field(default=100, ge=1, le=1000)
    max_events: Optional[int] = Field(default=None, ge=1)

    target_topics: Optional[Dict[EventType, str]] = None
    target_file_path: Optional[str] = None

    skip_errors: bool = True
    retry_failed: bool = False
    retry_attempts: int = 3

    enable_progress_tracking: bool = True
    progress_callback: Optional[Callable] = None


class ReplaySession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    config: ReplayConfig
    status: ReplayStatus = ReplayStatus.CREATED

    total_events: int = 0
    replayed_events: int = 0
    failed_events: int = 0
    skipped_events: int = 0

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_event_at: Optional[datetime] = None

    errors: List[Dict[str, Any]] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True


class EventReplayService:
    _event_type_mapping: ClassVar[Dict[EventType, Type[BaseEvent]]] = {}
    _default_topic_mapping: ClassVar[Dict[EventType, str]] = {
        EventType.EXECUTION_REQUESTED: "execution-requests",
        EventType.EXECUTION_STARTED: "execution-events",
        EventType.EXECUTION_COMPLETED: "execution-events",
        EventType.EXECUTION_FAILED: "execution-events",
        EventType.POD_CREATED: "pod-events",
        EventType.POD_SCHEDULED: "pod-events",
        EventType.POD_RUNNING: "pod-events",
        EventType.POD_SUCCEEDED: "pod-events",
        EventType.POD_FAILED: "pod-events",
    }

    def __init__(
        self,
        database: AsyncIOMotorDatabase,
        producer: UnifiedProducer,
        event_store: EventStore
    ) -> None:
        self._sessions: Dict[str, ReplaySession] = {}
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._producer = producer
        self._event_store = event_store
        self._db = database
        self._callbacks: Dict[ReplayTarget, Callable] = {}
        self._file_locks: Dict[str, asyncio.Lock] = {}
        self._initialize_event_type_mapping()
        logger.info("Event replay service initialized")

    async def initialize_indexes(self) -> None:
        """Initialize database indexes - should be called during startup"""
        await self._create_indexes()

    async def _create_indexes(self) -> None:
        if self._db is None:
            return

        events_collection = self._db.events
        await events_collection.create_index([("execution_id", 1), ("timestamp", 1)])
        await events_collection.create_index([("event_type", 1), ("timestamp", 1)])
        await events_collection.create_index([("metadata.user_id", 1), ("timestamp", 1)])

    def _initialize_event_type_mapping(self) -> None:
        """Initialize event type mapping from the central registry."""
        EventReplayService._event_type_mapping = build_event_type_mapping()

    async def create_replay_session(self, config: ReplayConfig) -> str:
        session = ReplaySession(config=config)
        self._sessions[session.session_id] = session

        logger.info(
            f"Created replay session {session.session_id} "
            f"type={config.replay_type} target={config.target}"
        )

        return session.session_id

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

        ACTIVE_REPLAYS.inc()
        logger.info(f"Started replay session {session_id}")

    async def _run_replay(self, session: ReplaySession) -> None:
        start_time = asyncio.get_event_loop().time()

        try:
            with trace_span(
                    name="event_replay.session",
                    kind=SpanKind.INTERNAL,
                    attributes={
                        "replay.session_id": str(session.session_id),
                        "replay.type": session.config.replay_type,
                        "replay.target": session.config.target,
                    }
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
            ACTIVE_REPLAYS.dec()
            self._active_tasks.pop(session.session_id, None)

    async def _prepare_session(self, session: ReplaySession) -> None:
        total_count = await self._count_events(session.config.filter)
        session.total_events = min(
            total_count,
            session.config.max_events or total_count
        )

        logger.info(
            f"Replay session {session.session_id} will process "
            f"{session.total_events} events"
        )

    async def _handle_progress_callback(self, session: ReplaySession) -> None:
        if session.config.progress_callback:
            try:
                await session.config.progress_callback(session)
            except Exception as e:
                logger.error(f"Progress callback error: {e}")

    async def _complete_session(self, session: ReplaySession, start_time: float) -> None:
        if session.status == ReplayStatus.RUNNING:
            session.status = ReplayStatus.COMPLETED
            session.completed_at = datetime.now(timezone.utc)

            duration = asyncio.get_event_loop().time() - start_time
            REPLAY_DURATION.labels(
                replay_type=session.config.replay_type
            ).observe(duration)

            logger.info(
                f"Replay session {session.session_id} completed. "
                f"Replayed: {session.replayed_events}, "
                f"Failed: {session.failed_events}, "
                f"Skipped: {session.skipped_events}, "
                f"Duration: {duration:.2f}s"
            )

    async def _handle_session_error(self, session: ReplaySession, error: Exception) -> None:
        logger.error(
            f"Replay session {session.session_id} failed: {error}",
            exc_info=True
        )
        session.status = ReplayStatus.FAILED
        session.errors.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(error),
            "type": type(error).__name__
        })
        REPLAY_ERRORS.labels(error_type=type(error).__name__).inc()

    async def _count_events(self, filter: ReplayFilter) -> int:
        query = filter.to_mongo_query()
        if self._db is None:
            raise RuntimeError("Database not initialized")
        count = await self._db.events.count_documents(query)
        return count

    async def _deserialize_event(
            self,
            doc: Dict[str, Any],
            session: ReplaySession
    ) -> Optional[BaseEvent]:
        try:
            event_type = EventType(doc["event_type"])
            event_class = self._get_event_class(event_type)
            if event_class:
                return event_class(**doc)
            else:
                logger.warning(f"Unknown event type: {event_type}")
                session.skipped_events += 1
                return None
        except Exception as e:
            logger.error(f"Failed to deserialize event: {e}")
            session.failed_events += 1
            if not session.config.skip_errors:
                raise
            return None

    async def _apply_replay_delay(
            self,
            session: ReplaySession,
            event: BaseEvent
    ) -> None:
        if session.last_event_at and session.config.speed_multiplier < 100:
            time_diff = (event.timestamp - session.last_event_at).total_seconds()
            delay = time_diff / session.config.speed_multiplier
            if delay > 0:
                await asyncio.sleep(delay)

    def _update_replay_metrics(
            self,
            session: ReplaySession,
            event: BaseEvent,
            success: bool
    ) -> None:
        if success:
            session.replayed_events += 1
            status = "success"
        else:
            session.failed_events += 1
            status = "failed"

        EVENTS_REPLAYED.labels(
            replay_type=session.config.replay_type,
            event_type=event.event_type,
            status=status
        ).inc()

    async def _handle_replay_error(
            self,
            session: ReplaySession,
            event: BaseEvent,
            error: Exception
    ) -> None:
        logger.error(f"Failed to replay event {event.event_id}: {error}")
        session.failed_events += 1
        session.errors.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_id": str(event.event_id),
            "error": str(error)
        })

    async def _replay_to_kafka(
            self,
            session: ReplaySession,
            event: BaseEvent
    ) -> bool:
        config = session.config
        topic = self._get_target_topic(event, config)
        if not topic:
            logger.warning(f"No target topic for event type {event.event_type}")
            return False

        if not config.preserve_timestamps:
            event.timestamp = datetime.now(timezone.utc)

        # Add replay metadata to the event's payload or as additional context
        # Since EventMetadata doesn't have these fields, we'll handle replay tracking differently
        # The replay information should be tracked in the session, not in the event metadata

        if not self._producer:
            raise RuntimeError("Producer not initialized")
        
        # Send the event without modifying its metadata structure
        result = await self._producer.send_event(event, topic)
        return result is not None

    async def _replay_to_callback(
            self,
            event: BaseEvent,
            session: ReplaySession
    ) -> bool:
        callback = self._callbacks.get(ReplayTarget.CALLBACK)
        if callback:
            await callback(event, session)
            return True
        return False

    async def _replay_to_file(
            self,
            event: BaseEvent,
            file_path: Optional[str]
    ) -> bool:
        if not file_path:
            logger.error("No target file path specified")
            return False
        await self._write_event_to_file(event, file_path)
        return True

    async def _retry_replay(
            self,
            session: ReplaySession,
            event: BaseEvent,
            error: Exception
    ) -> bool:
        for attempt in range(session.config.retry_attempts):
            try:
                await asyncio.sleep(min(2 ** attempt, 10))
                return await self._replay_event(session, event)
            except Exception:
                if attempt == session.config.retry_attempts - 1:
                    return False
        return False

    async def _fetch_event_batches(
            self,
            session: ReplaySession
    ) -> AsyncIterator[List[BaseEvent]]:
        query = session.config.filter.to_mongo_query()
        batch_size = session.config.batch_size
        if self._db is None:
            raise RuntimeError("Database not initialized")
        cursor = self._db.events.find(query).sort("timestamp", 1)

        if session.config.max_events:
            cursor = cursor.limit(session.config.max_events)

        batch: List[BaseEvent] = []
        async for doc in cursor:
            event = await self._deserialize_event(doc, session)
            if event:
                batch.append(event)
                if len(batch) >= batch_size:
                    yield batch
                    batch = []

        if batch:
            yield batch

    async def _process_batch(
            self,
            session: ReplaySession,
            batch: List[BaseEvent]
    ) -> None:
        for event in batch:
            if session.status != ReplayStatus.RUNNING:
                break

            try:
                await self._apply_replay_delay(session, event)
                success = await self._replay_event(session, event)
                self._update_replay_metrics(session, event, success)
                session.last_event_at = event.timestamp
            except Exception as e:
                await self._handle_replay_error(session, event, e)
                if not session.config.skip_errors:
                    raise

    async def _replay_event(
            self,
            session: ReplaySession,
            event: BaseEvent
    ) -> bool:
        config = session.config

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
            logger.error(f"Failed to replay event: {e}")
            if config.retry_failed:
                return await self._retry_replay(session, event, e)
            raise

    def _get_target_topic(
            self,
            event: BaseEvent,
            config: ReplayConfig
    ) -> Optional[str]:
        if config.target_topics:
            return config.target_topics.get(event.event_type)
        return self._default_topic_mapping.get(event.event_type, "replay-events")

    async def _write_event_to_file(
            self,
            event: BaseEvent,
            file_path: str
    ) -> None:
        if file_path not in self._file_locks:
            self._file_locks[file_path] = asyncio.Lock()

        async with self._file_locks[file_path]:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._write_to_file_sync,
                event,
                file_path
            )

    def _write_to_file_sync(
            self,
            event: BaseEvent,
            file_path: str
    ) -> None:
        with open(file_path, 'a') as f:
            f.write(json.dumps(event.model_dump(), default=str) + '\n')

    def _get_event_class(self, event_type: EventType) -> Optional[Type[BaseEvent]]:
        return self._event_type_mapping.get(event_type)

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

    def get_session(self, session_id: str) -> Optional[ReplaySession]:
        return self._sessions.get(session_id)

    def list_sessions(
            self,
            status: Optional[ReplayStatus] = None,
            limit: int = 100
    ) -> List[ReplaySession]:
        sessions = list(self._sessions.values())

        if status:
            sessions = [s for s in sessions if s.status == status]

        sessions.sort(key=lambda s: s.created_at, reverse=True)
        return sessions[:limit]

    def register_callback(
            self,
            target: ReplayTarget,
            callback: Callable[[BaseEvent, ReplaySession], Any]
    ) -> None:
        self._callbacks[target] = callback

    async def cleanup_old_sessions(
            self,
            older_than_hours: int = 24
    ) -> int:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        removed = 0

        completed_statuses = {
            ReplayStatus.COMPLETED,
            ReplayStatus.FAILED,
            ReplayStatus.CANCELLED
        }

        for session_id in list(self._sessions.keys()):
            session = self._sessions[session_id]
            if (
                    session.status in completed_statuses
                    and session.created_at < cutoff_time
            ):
                del self._sessions[session_id]
                removed += 1

        logger.info(f"Cleaned up {removed} old replay sessions")
        return removed
