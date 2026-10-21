import time
from datetime import datetime, timezone
from typing import Any

import structlog
from opentelemetry import trace
from opentelemetry.util.types import AttributeValue
from pydantic import ValidationError
from redis.exceptions import RedisError

from app.db import ReplayRepository
from app.db.docs import ReplaySessionDocument
from app.domain.enums import ReplayStatus
from app.domain.events import DomainEventAdapter
from app.domain.replay import ReplayError
from app.domain.sse import DomainReplaySSEPayload
from app.events import PRODUCE_ERRORS, UnifiedProducer
from app.services.sse.redis_bus import SSERedisBus

_BATCH_SIZE = 100
_SEND_ERRORS: tuple[type[Exception], ...] = (ValidationError, *PRODUCE_ERRORS)


class EventReplayService:
    """Runs replay sessions in the worker: sends the stored events a session matches to Kafka again, in order.

    The API stores a session as scheduled, and a worker job claims the oldest one and runs it to the end.
    """

    def __init__(
        self,
        repository: ReplayRepository,
        producer: UnifiedProducer,
        sse_bus: SSERedisBus,
        logger: structlog.stdlib.BoundLogger,
        tracer: trace.Tracer,
    ) -> None:
        self._repository = repository
        self._producer = producer
        self._sse_bus = sse_bus
        self.logger = logger
        self._tracer = tracer

    async def fail_interrupted_sessions(self) -> None:
        """Fail the sessions a worker restart cut off, since a replay doesn't pick up where it stopped."""
        for session in await self._repository.get_running_sessions():
            session.errors.append(
                ReplayError(timestamp=datetime.now(timezone.utc), error="The worker restarted during the replay")
            )
            await self._finish(session, ReplayStatus.FAILED)

    async def run_next_session(self) -> None:
        """Run the oldest scheduled session to the end; an unexpected error fails it, then propagates."""
        session = await self._repository.get_oldest_scheduled_session()
        if session is None:
            return
        session.status = ReplayStatus.RUNNING
        session.started_at = datetime.now(timezone.utc)
        await self._repository.save_session(session)
        self._report_status_change(ReplayStatus.SCHEDULED, ReplayStatus.RUNNING)
        await self._publish_status(session)
        try:
            await self._replay(session)
        except Exception as e:
            session.errors.append(
                ReplayError(timestamp=datetime.now(timezone.utc), error=str(e), error_type=type(e).__name__)
            )
            await self._finish(session, ReplayStatus.FAILED)
            raise
        await self._finish(session, ReplayStatus.COMPLETED)

    async def report_sessions(self) -> None:
        """Report the stored sessions per status, for the collector's gauge."""
        counts = await self._repository.count_by_status()
        for status in ReplayStatus:
            attributes: dict[str, AttributeValue] = {"replay.status": status, "replay.sessions": counts.get(status, 0)}
            self._tracer.start_span("replay.sessions", attributes=attributes).end()

    async def _replay(self, session: ReplaySessionDocument) -> None:
        sent = 0
        async for batch in self._repository.fetch_events(session.config.filter, _BATCH_SIZE):
            self._tracer.start_span("replay.batch", attributes={"replay.batch_size": len(batch)}).end()
            for doc in batch:
                if sent >= session.config.max_events:
                    return
                sent += 1
                await self._send(session, doc)

    async def _send(self, session: ReplaySessionDocument, doc: dict[str, Any]) -> None:
        """Send one stored event again, stamped now; a failure counts against the session and the replay goes on."""
        t0 = time.monotonic()
        replayed = False
        try:
            event = DomainEventAdapter.validate_python(doc | {"timestamp": datetime.now(timezone.utc)})
            await self._producer.produce(event_to_produce=event, key=event.aggregate_id or event.event_id)
            replayed = True
        except _SEND_ERRORS as e:
            self.logger.warning("Failed to replay event", event_id=doc["event_id"], error=str(e))
            session.errors.append(
                ReplayError(
                    timestamp=datetime.now(timezone.utc),
                    error=str(e),
                    error_type=type(e).__name__,
                    event_id=doc["event_id"],
                )
            )

        if replayed:
            session.replayed_events += 1
        else:
            session.failed_events += 1
        await self._repository.save_session(session)
        await self._publish_status(session)

        attributes: dict[str, AttributeValue] = {
            "replay.event_type": doc["event_type"],
            "replay.result": "replayed" if replayed else "failed",
            "replay.processing_seconds": time.monotonic() - t0,
        }
        self._tracer.start_span("replay.event", attributes=attributes).end()

    async def _finish(self, session: ReplaySessionDocument, status: ReplayStatus) -> None:
        session.status = status
        session.completed_at = datetime.now(timezone.utc)
        self._report_status_change(ReplayStatus.RUNNING, status)
        if status == ReplayStatus.COMPLETED and session.started_at:
            duration = (session.completed_at - session.started_at).total_seconds()
            total_events = session.replayed_events + session.failed_events
            attributes: dict[str, AttributeValue] = {"replay.duration_seconds": duration}
            if total_events > 0 and duration > 0:
                attributes["replay.throughput"] = total_events / duration
            self._tracer.start_span("replay.session_completed", attributes=attributes).end()
        await self._repository.save_session(session)
        await self._publish_status(session)
        self.logger.info(
            "Replay session finished",
            session_id=session.session_id,
            status=session.status,
            replayed_events=session.replayed_events,
            failed_events=session.failed_events,
        )

    def _report_status_change(self, from_status: ReplayStatus, to_status: ReplayStatus) -> None:
        attributes = {"replay.from_status": from_status, "replay.to_status": to_status}
        self._tracer.start_span("replay.status_change", attributes=attributes).end()

    async def _publish_status(self, session: ReplaySessionDocument) -> None:
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
