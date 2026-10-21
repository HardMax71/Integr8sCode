import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from typing import Any

import structlog
from opentelemetry import trace

from app.db import AdminEventsRepository, ReplayRepository
from app.db.docs import ReplaySessionDocument
from app.domain.admin import ReplaySessionData
from app.domain.enums import ExportFormat, ReplayStatus
from app.domain.events import (
    EventBrowseResult,
    EventDetail,
    EventExportRow,
    EventFilter,
    EventNotFoundError,
    EventStatistics,
    EventSummary,
)
from app.domain.exceptions import NotFoundError, ValidationError
from app.domain.replay import ReplayConfig, ReplayFilter, ReplaySessionNotFoundError
from app.domain.sse import DomainReplaySSEPayload


def _export_row_to_dict(row: EventExportRow) -> dict[str, str]:
    """Convert EventExportRow to dict with CSV column names."""
    meta = row.metadata
    return {
        "Event ID": row.event_id,
        "Event Type": row.event_type,
        "Timestamp": row.timestamp.isoformat(),
        "Aggregate ID": row.aggregate_id or "",
        "User ID": meta.user_id if meta and meta.user_id else "",
        "Service": meta.service_name if meta else "",
        "Status": "",
        "Error": "",
    }


def _filter_to_json_dict(f: EventFilter) -> dict[str, Any]:
    """Convert EventFilter to a JSON-safe dict (non-None fields only)."""
    d: dict[str, Any] = {}
    if f.event_types:
        d["event_types"] = list(f.event_types)
    if f.aggregate_id:
        d["aggregate_id"] = f.aggregate_id
    if f.user_id:
        d["user_id"] = f.user_id
    if f.service_name:
        d["service_name"] = f.service_name
    if f.start_time:
        d["start_time"] = f.start_time.isoformat()
    if f.end_time:
        d["end_time"] = f.end_time.isoformat()
    if f.search_text:
        d["search_text"] = f.search_text
    if f.status:
        d["status"] = f.status
    return d


class AdminReplayResult:
    def __init__(
        self,
        *,
        dry_run: bool,
        total_events: int,
        replay_id: str,
        status: ReplayStatus,
        session_id: str | None = None,
        events_preview: list[EventSummary] | None = None,
    ) -> None:
        self.dry_run = dry_run
        self.total_events = total_events
        self.replay_id = replay_id
        self.status = status
        self.session_id = session_id
        self.events_preview = events_preview


@dataclass
class ExportResult:
    file_name: str  # not 'filename' - conflicts with LogRecord reserved attribute
    content: str
    media_type: str


class AdminEventsService:
    def __init__(
        self,
        repository: AdminEventsRepository,
        replay_repository: ReplayRepository,
        logger: structlog.stdlib.BoundLogger,
        tracer: trace.Tracer,
    ) -> None:
        self._repo = repository
        self._replay_repository = replay_repository
        self.logger = logger
        self._tracer = tracer

    async def browse_events(
        self,
        *,
        event_filter: EventFilter,
        skip: int,
        limit: int,
    ) -> EventBrowseResult:
        return await self._repo.get_events_page(event_filter, skip=skip, limit=limit)

    async def get_event_detail(self, event_id: str) -> EventDetail:
        detail = await self._repo.get_event_detail(event_id)
        if not detail:
            self.logger.warning("Event not found", event_id=event_id)
            raise EventNotFoundError(event_id)
        return detail

    async def get_event_stats(self, *, hours: int) -> EventStatistics:
        return await self._repo.get_event_stats(hours=hours)

    async def prepare_or_schedule_replay(
        self,
        *,
        replay_filter: ReplayFilter,
        dry_run: bool,
        replay_id: str,
    ) -> AdminReplayResult:
        if replay_filter.is_empty():
            raise ValidationError("Must specify at least one filter for replay")

        self.logger.info(
            "Preparing replay session",
            dry_run=dry_run,
            replay_id=replay_id,
        )

        event_count = await self._repo.count_events_for_replay(replay_filter)
        if event_count == 0:
            raise NotFoundError("Events", "matching criteria")

        max_events = 1000
        if event_count > max_events and not dry_run:
            raise ValidationError(f"Too many events to replay ({event_count}). Maximum is {max_events}.")

        events_preview: list[EventSummary] = []
        if dry_run:
            events_preview = await self._repo.get_events_preview_for_replay(replay_filter, limit=100)

        session_data = ReplaySessionData(
            total_events=event_count,
            replay_id=replay_id,
            dry_run=dry_run,
            filter=replay_filter,
            events_preview=events_preview,
        )

        if dry_run:
            result = AdminReplayResult(
                dry_run=True,
                total_events=session_data.total_events,
                replay_id=replay_id,
                status=ReplayStatus.PREVIEW,
                events_preview=session_data.events_preview,
            )
            self.logger.info(
                "Replay dry-run prepared",
                total_events=result.total_events,
                replay_id=result.replay_id,
            )
            return result

        # The worker's replay job picks the session up and sends the events to Kafka
        session = ReplaySessionDocument(
            config=ReplayConfig(filter=replay_filter, max_events=max_events),
            total_events=event_count,
            replay_id=replay_id,
        )
        await self._replay_repository.create_session(session)
        self._tracer.start_span("replay.session_created").end()

        result = AdminReplayResult(
            dry_run=False,
            total_events=event_count,
            replay_id=replay_id,
            session_id=session.session_id,
            status=ReplayStatus.SCHEDULED,
        )
        self.logger.info(
            "Replay scheduled",
            session_id=result.session_id,
            total_events=result.total_events,
            replay_id=result.replay_id,
        )
        return result

    async def get_replay_sse_status(self, session_id: str) -> DomainReplaySSEPayload:
        status = await self._repo.get_replay_session_sse_status(session_id)
        if not status:
            self.logger.warning("Replay session not found", session_id=session_id)
            raise ReplaySessionNotFoundError(session_id)
        return status

    async def export_events(
        self, *, event_filter: EventFilter, limit: int, export_format: ExportFormat
    ) -> ExportResult:
        if export_format == ExportFormat.CSV:
            return await self._export_csv(event_filter=event_filter, limit=limit)
        return await self._export_json(event_filter=event_filter, limit=limit)

    async def _export_csv(self, *, event_filter: EventFilter, limit: int) -> ExportResult:
        events = await self._repo.get_events(event_filter, skip=0, limit=limit)
        rows = [
            EventExportRow(
                event_id=e.event_id,
                event_type=e.event_type,
                timestamp=e.timestamp,
                aggregate_id=e.aggregate_id,
                metadata=e.metadata,
            )
            for e in events
        ]
        output = StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "Event ID",
                "Event Type",
                "Timestamp",
                "Aggregate ID",
                "User ID",
                "Service",
                "Status",
                "Error",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(_export_row_to_dict(row))
        output.seek(0)
        filename = f"events_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        self.logger.info(
            "Exported events CSV",
            row_count=len(rows),
            file_name=filename,
        )
        return ExportResult(file_name=filename, content=output.getvalue(), media_type="text/csv")

    async def _export_json(self, *, event_filter: EventFilter, limit: int) -> ExportResult:
        events = await self._repo.get_events(event_filter, skip=0, limit=limit)
        # mode="json" auto-converts datetime fields to ISO strings
        events_data = [event.model_dump(mode="json") for event in events]

        export_data: dict[str, Any] = {
            "export_metadata": {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "total_events": len(events_data),
                "filters_applied": _filter_to_json_dict(event_filter),
                "export_limit": limit,
            },
            "events": events_data,
        }
        json_content = json.dumps(export_data, indent=2)
        filename = f"events_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        self.logger.info(
            "Exported events JSON",
            event_count=len(events_data),
            file_name=filename,
        )
        return ExportResult(file_name=filename, content=json_content, media_type="application/json")

    async def delete_event(self, *, event_id: str, deleted_by: str) -> None:
        # Load event for archival; archive then delete
        self.logger.warning("Admin attempting to delete event", event_id=event_id, deleted_by=deleted_by)
        detail = await self.get_event_detail(event_id)
        await self._repo.archive_event(detail.event, deleted_by)
        if not await self._repo.delete_event(event_id):
            self.logger.warning("Event vanished before deletion", event_id=event_id)
            raise EventNotFoundError(event_id)
        self.logger.info(
            "Event deleted",
            event_id=event_id,
            event_type=detail.event.event_type,
            deleted_by=deleted_by,
        )
