import csv
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Any

import structlog
from pydantic import TypeAdapter

from app.db.docs.replay import ReplaySessionDocument
from app.db.repositories import AdminEventsRepository
from app.domain.admin import ReplaySessionData, ReplaySessionStatusDetail, ReplaySessionUpdate
from app.domain.enums import ExportFormat, ReplayStatus, ReplayTarget, ReplayType
from app.domain.events import (
    EventBrowseResult,
    EventDetail,
    EventExportRow,
    EventFilter,
    EventStatistics,
    EventSummary,
)
from app.domain.exceptions import NotFoundError, ValidationError
from app.domain.replay import ReplayConfig, ReplayFilter
from app.services.event_replay import EventReplayService

_export_row_ta = TypeAdapter(EventExportRow)
_event_filter_ta = TypeAdapter(EventFilter)


def _export_row_to_dict(row: EventExportRow) -> dict[str, str]:
    """Convert EventExportRow to dict with CSV column names."""
    data = _export_row_ta.dump_python(row, mode="json")
    meta = data.get("metadata", {})
    return {
        "Event ID": data["event_id"],
        "Event Type": data["event_type"],
        "Timestamp": data["timestamp"],
        "Aggregate ID": data.get("aggregate_id") or "",
        "User ID": meta.get("user_id") or "",
        "Service": meta.get("service_name", ""),
        "Status": "",
        "Error": "",
    }


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
            replay_service: EventReplayService,
            logger: structlog.stdlib.BoundLogger,
    ) -> None:
        self._repo = repository
        self._replay_service = replay_service
        self.logger = logger

    async def browse_events(
            self,
            *,
            event_filter: EventFilter,
            skip: int,
            limit: int,
    ) -> EventBrowseResult:
        return await self._repo.get_events_page(event_filter, skip=skip, limit=limit)

    async def get_event_detail(self, event_id: str) -> EventDetail | None:
        return await self._repo.get_event_detail(event_id)

    async def get_event_stats(self, *, hours: int) -> EventStatistics:
        return await self._repo.get_event_stats(hours=hours)

    async def prepare_or_schedule_replay(
            self,
            *,
            replay_filter: ReplayFilter,
            dry_run: bool,
            replay_id: str,
            target_service: str | None,
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

        # Build config for actual replay - filter is already unified, just pass it
        config = ReplayConfig(
            replay_type=ReplayType.QUERY,
            target=ReplayTarget.KAFKA if target_service else ReplayTarget.TEST,
            filter=replay_filter,
            speed_multiplier=1.0,
            preserve_timestamps=False,
            batch_size=100,
            max_events=1000,
            skip_errors=True,
        )

        op = await self._replay_service.create_session_from_config(config)
        session_id = op.session_id

        # Persist additional metadata to the admin replay session record
        session_update = ReplaySessionUpdate(
            total_events=session_data.total_events,
            replay_id=replay_id,
            status=ReplayStatus.SCHEDULED,
        )
        await self._repo.update_replay_session(
            session_id=session_id,
            updates=session_update,
        )

        result = AdminReplayResult(
            dry_run=False,
            total_events=session_data.total_events,
            replay_id=replay_id,
            session_id=session_id,
            status=ReplayStatus.SCHEDULED,
        )
        self.logger.info(
            "Replay scheduled",
            session_id=result.session_id,
            total_events=result.total_events,
            replay_id=result.replay_id,
        )
        return result

    async def start_replay_session(self, session_id: str) -> None:
        await self._replay_service.start_session(session_id)

    async def get_replay_status(self, session_id: str) -> ReplaySessionStatusDetail | None:
        doc = await self._repo.get_replay_session_doc(session_id)
        if not doc:
            return None

        result = ReplaySessionStatusDetail.model_validate(doc)
        result.estimated_completion = self._estimate_completion(doc, datetime.now(timezone.utc))
        result.execution_results = await self._repo.get_execution_results_for_filter(doc.config.filter)
        return result

    def _estimate_completion(self, doc: ReplaySessionDocument, now: datetime) -> datetime | None:
        if not doc.is_running or not doc.started_at or doc.replayed_events <= 0:
            return None
        elapsed = (now - doc.started_at).total_seconds()
        if elapsed <= 0:
            return None
        rate = doc.replayed_events / elapsed
        remaining = doc.total_events - doc.replayed_events
        return now + timedelta(seconds=remaining / rate) if rate > 0 else None

    async def export_events(
            self, *, event_filter: EventFilter, limit: int, export_format: ExportFormat
    ) -> ExportResult:
        if export_format == ExportFormat.CSV:
            return await self._export_csv(event_filter=event_filter, limit=limit)
        return await self._export_json(event_filter=event_filter, limit=limit)

    async def _export_csv(self, *, event_filter: EventFilter, limit: int) -> ExportResult:
        events = await self._repo.get_events(event_filter, skip=0, limit=limit)
        rows = [_export_row_ta.validate_python(e.model_dump()) for e in events]
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
                "filters_applied": _event_filter_ta.dump_python(event_filter, mode="json"),
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

    async def delete_event(self, *, event_id: str, deleted_by: str) -> bool:
        # Load event for archival; archive then delete
        self.logger.warning("Admin attempting to delete event", event_id=event_id, deleted_by=deleted_by)
        detail = await self._repo.get_event_detail(event_id)
        if not detail:
            return False
        await self._repo.archive_event(detail.event, deleted_by)
        deleted = await self._repo.delete_event(event_id)
        if deleted:
            self.logger.info(
                "Event deleted",
                event_id=event_id,
                event_type=detail.event.event_type,
                deleted_by=deleted_by,
            )
        return deleted
