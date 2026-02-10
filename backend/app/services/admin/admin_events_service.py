import csv
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Any

from app.db.docs.replay import ReplaySessionDocument
from app.db.repositories import AdminEventsRepository
from app.domain.admin import ReplaySessionData, ReplaySessionStatusDetail, ReplaySessionUpdate
from app.domain.enums import ReplayStatus, ReplayTarget, ReplayType
from app.domain.events import (
    EventBrowseResult,
    EventDetail,
    EventExportRow,
    EventFilter,
    EventStatistics,
    EventSummary,
)
from app.domain.exceptions import NotFoundError, ValidationError
from app.domain.replay import ReplayConfig, ReplayFilter, ReplaySessionState
from app.services.event_replay import EventReplayService


def _export_row_to_dict(row: EventExportRow) -> dict[str, str]:
    """Convert EventExportRow to dict with CSV column names."""
    data = row.model_dump(mode="json")
    meta = data.get("metadata", {})
    return {
        "Event ID": data["event_id"],
        "Event Type": data["event_type"],
        "Timestamp": data["timestamp"],
        "Correlation ID": meta.get("correlation_id") or "",
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
        replay_correlation_id: str,
        status: ReplayStatus,
        session_id: str | None = None,
        events_preview: list[EventSummary] | None = None,
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
        self, repository: AdminEventsRepository, replay_service: EventReplayService, logger: logging.Logger
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
        replay_correlation_id: str,
        target_service: str | None,
    ) -> AdminReplayResult:
        if replay_filter.is_empty():
            raise ValidationError("Must specify at least one filter for replay")

        self.logger.info(
            "Preparing replay session",
            extra={
                "dry_run": dry_run,
                "replay_correlation_id": replay_correlation_id,
            },
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
            replay_correlation_id=replay_correlation_id,
            dry_run=dry_run,
            filter=replay_filter,
            events_preview=events_preview,
        )

        if dry_run:
            result = AdminReplayResult(
                dry_run=True,
                total_events=session_data.total_events,
                replay_correlation_id=replay_correlation_id,
                status=ReplayStatus.PREVIEW,
                events_preview=session_data.events_preview,
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
        doc = await self._repo.get_replay_session_doc(session_id)
        if not doc:
            return None

        now = datetime.now(timezone.utc)
        changed = self._advance_replay_state(doc, now)
        if changed:
            await doc.save()

        estimated_completion = self._estimate_completion(doc, now)
        session = ReplaySessionState.model_validate(doc)
        execution_results = await self._repo.get_execution_results_for_filter(doc.config.filter)

        return ReplaySessionStatusDetail(
            session=session,
            estimated_completion=estimated_completion,
            execution_results=execution_results,
        )

    def _advance_replay_state(self, doc: ReplaySessionDocument, now: datetime) -> bool:
        """Advance replay state machine. Returns True if doc was mutated."""
        if doc.status == ReplayStatus.SCHEDULED and doc.created_at:
            if (now - doc.created_at).total_seconds() > 2:
                doc.status = ReplayStatus.RUNNING
                doc.started_at = now
                return True

        if not doc.is_running or not doc.started_at:
            return False

        elapsed = (now - doc.started_at).total_seconds()
        doc.replayed_events = min(int(elapsed * 10), doc.total_events)
        if doc.replayed_events >= doc.total_events:
            doc.status = ReplayStatus.COMPLETED
            doc.completed_at = now
        return True

    def _estimate_completion(self, doc: ReplaySessionDocument, now: datetime) -> datetime | None:
        if not doc.is_running or not doc.started_at or doc.replayed_events <= 0:
            return None
        elapsed = (now - doc.started_at).total_seconds()
        if elapsed <= 0:
            return None
        rate = doc.replayed_events / elapsed
        remaining = doc.total_events - doc.replayed_events
        return now + timedelta(seconds=remaining / rate) if rate > 0 else None

    async def export_events_csv_content(self, *, event_filter: EventFilter, limit: int) -> ExportResult:
        events = await self._repo.get_events(event_filter, skip=0, limit=limit)
        rows = [EventExportRow.model_validate(e, from_attributes=True) for e in events]
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
        for row in rows:
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
        events = await self._repo.get_events(event_filter, skip=0, limit=limit)
        # mode="json" auto-converts datetime fields to ISO strings
        events_data = [event.model_dump(mode="json") for event in events]

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
