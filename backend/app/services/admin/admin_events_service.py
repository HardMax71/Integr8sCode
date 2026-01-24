import csv
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from typing import Any, Dict, List

from beanie.odm.enums import SortDirection

from app.db.repositories.admin import AdminEventsRepository
from app.domain.admin import ReplaySessionStatusDetail
from app.domain.admin.replay_updates import ReplaySessionUpdate
from app.domain.enums.replay import ReplayStatus, ReplayTarget, ReplayType
from app.domain.events.event_models import (
    EventBrowseResult,
    EventDetail,
    EventExportRow,
    EventFilter,
    EventStatistics,
)
from app.domain.replay import ReplayConfig, ReplayFilter
from app.services.replay_service import ReplayService


def _export_row_to_dict(row: EventExportRow) -> dict[str, str]:
    """Convert EventExportRow to dict with display names."""
    # Use mode="json" to auto-convert datetime to ISO string
    data = row.model_dump(mode="json")
    return {
        "Event ID": data["event_id"],
        "Event Type": data["event_type"],
        "Timestamp": data["timestamp"],
        "Correlation ID": data["correlation_id"],
        "Aggregate ID": data["aggregate_id"],
        "User ID": data["user_id"],
        "Service": data["service"],
        "Status": data["status"],
        "Error": data["error"],
    }


class AdminReplayResult:
    def __init__(
        self,
        *,
        dry_run: bool,
        total_events: int,
        replay_correlation_id: str,
        status: ReplayStatus,
        session_id: str | None = None,
        events_preview: List[Dict[str, Any]] | None = None,
    ) -> None:
        self.dry_run = dry_run
        self.total_events = total_events
        self.replay_correlation_id = replay_correlation_id
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
        self, repository: AdminEventsRepository, replay_service: ReplayService, logger: logging.Logger
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
        sort_by: str,
        sort_order: int,
    ) -> EventBrowseResult:
        direction = SortDirection.DESCENDING if sort_order == -1 else SortDirection.ASCENDING
        return await self._repo.browse_events(
            event_filter=event_filter, skip=skip, limit=limit, sort_by=sort_by, sort_order=direction
        )

    async def get_event_detail(self, event_id: str) -> EventDetail | None:
        return await self._repo.get_event_detail(event_id)

    async def get_event_stats(self, *, hours: int) -> EventStatistics:
        return await self._repo.get_event_stats(hours=hours)

    async def prepare_or_schedule_replay(
        self,
        *,
        replay_filter: ReplayFilter,
        dry_run: bool,
        replay_correlation_id: str,
        target_service: str | None,
    ) -> AdminReplayResult:
        if replay_filter.is_empty():
            raise ValueError("Must specify at least one filter for replay")

        # Prepare and optionally preview
        self.logger.info(
            "Preparing replay session",
            extra={
                "dry_run": dry_run,
                "replay_correlation_id": replay_correlation_id,
            },
        )
        session_data = await self._repo.prepare_replay_session(
            replay_filter=replay_filter,
            dry_run=dry_run,
            replay_correlation_id=replay_correlation_id,
            max_events=1000,
        )

        if dry_run:
            # Map previews into simple dicts via repository summary mapper
            previews = [
                {
                    "event_id": e.event_id,
                    "event_type": e.event_type,
                    "timestamp": e.timestamp,
                    "aggregate_id": e.aggregate_id,
                }
                for e in session_data.events_preview
            ]
            result = AdminReplayResult(
                dry_run=True,
                total_events=session_data.total_events,
                replay_correlation_id=replay_correlation_id,
                status=ReplayStatus.PREVIEW,
                events_preview=previews,
            )
            self.logger.info(
                "Replay dry-run prepared",
                extra={
                    "total_events": result.total_events,
                    "replay_correlation_id": result.replay_correlation_id,
                },
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
            correlation_id=replay_correlation_id,
            status=ReplayStatus.SCHEDULED,
        )
        await self._repo.update_replay_session(
            session_id=session_id,
            updates=session_update,
        )

        result = AdminReplayResult(
            dry_run=False,
            total_events=session_data.total_events,
            replay_correlation_id=replay_correlation_id,
            session_id=session_id,
            status=ReplayStatus.SCHEDULED,
        )
        self.logger.info(
            "Replay scheduled",
            extra={
                "session_id": result.session_id,
                "total_events": result.total_events,
                "replay_correlation_id": result.replay_correlation_id,
            },
        )
        return result

    async def start_replay_session(self, session_id: str) -> None:
        await self._replay_service.start_session(session_id)

    async def get_replay_status(self, session_id: str) -> ReplaySessionStatusDetail | None:
        status = await self._repo.get_replay_status_with_progress(session_id)
        return status

    async def export_events_csv(self, event_filter: EventFilter) -> List[EventExportRow]:
        rows = await self._repo.export_events_csv(event_filter)
        return rows

    async def export_events_csv_content(self, *, event_filter: EventFilter, limit: int) -> ExportResult:
        rows = await self._repo.export_events_csv(event_filter)
        output = StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "Event ID",
                "Event Type",
                "Timestamp",
                "Correlation ID",
                "Aggregate ID",
                "User ID",
                "Service",
                "Status",
                "Error",
            ],
        )
        writer.writeheader()
        for row in rows[:limit]:
            writer.writerow(_export_row_to_dict(row))
        output.seek(0)
        filename = f"events_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        self.logger.info(
            "Exported events CSV",
            extra={
                "row_count": len(rows),
                "file_name": filename,
            },
        )
        return ExportResult(file_name=filename, content=output.getvalue(), media_type="text/csv")

    async def export_events_json_content(self, *, event_filter: EventFilter, limit: int) -> ExportResult:
        result = await self._repo.browse_events(
            event_filter=event_filter, skip=0, limit=limit, sort_by="timestamp", sort_order=SortDirection.DESCENDING
        )
        # mode="json" auto-converts datetime fields to ISO strings
        events_data = [event.model_dump(mode="json") for event in result.events]

        export_data: dict[str, Any] = {
            "export_metadata": {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "total_events": len(events_data),
                "filters_applied": event_filter.model_dump(mode="json"),
                "export_limit": limit,
            },
            "events": events_data,
        }
        json_content = json.dumps(export_data, indent=2)
        filename = f"events_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        self.logger.info(
            "Exported events JSON",
            extra={
                "event_count": len(events_data),
                "file_name": filename,
            },
        )
        return ExportResult(file_name=filename, content=json_content, media_type="application/json")

    async def delete_event(self, *, event_id: str, deleted_by: str) -> bool:
        # Load event for archival; archive then delete
        self.logger.warning("Admin attempting to delete event", extra={"event_id": event_id, "deleted_by": deleted_by})
        detail = await self._repo.get_event_detail(event_id)
        if not detail:
            return False
        await self._repo.archive_event(detail.event, deleted_by)
        deleted = await self._repo.delete_event(event_id)
        if deleted:
            correlation_id = detail.event.metadata.correlation_id
            self.logger.info(
                "Event deleted",
                extra={
                    "event_id": event_id,
                    "event_type": detail.event.event_type,
                    "correlation_id": correlation_id,
                    "deleted_by": deleted_by,
                },
            )
        return deleted
