from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import structlog
from app.db import UserSettingsRepository
from app.domain.enums import EventType, Theme
from app.domain.events import DomainEvent
from app.domain.user import DomainUserSettings, DomainUserSettingsChangedEvent
from app.services.kafka_event_service import KafkaEventService
from app.services.user_settings_service import UserSettingsService
from app.settings import Settings

pytestmark = pytest.mark.unit

_event_fields = set(DomainUserSettingsChangedEvent.__dataclass_fields__)


class _MemoryRepo(UserSettingsRepository):
    def __init__(self) -> None:
        self.snapshot: DomainUserSettings | None = None
        self.events: list[DomainUserSettingsChangedEvent] = []

    async def get_snapshot(self, user_id: str) -> DomainUserSettings | None:
        return self.snapshot

    async def create_snapshot(self, settings: DomainUserSettings) -> None:
        self.snapshot = settings

    async def get_settings_events(
        self,
        user_id: str,
        event_types: list[EventType],
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
        newest_first: bool = False,
    ) -> list[DomainUserSettingsChangedEvent]:
        events = [
            e for e in self.events if (since is None or e.timestamp > since) and (until is None or e.timestamp <= until)
        ]
        events.sort(key=lambda e: e.timestamp, reverse=newest_first)
        return events[:limit] if limit else events

    async def count_events_since_snapshot(self, user_id: str) -> int:
        return 0


def _changed(at: datetime, **changes: object) -> DomainUserSettingsChangedEvent:
    return DomainUserSettingsChangedEvent(
        event_id=f"ev-{at.timestamp()}",
        event_type=EventType.USER_SETTINGS_UPDATED,
        timestamp=at,
        user_id="u1",
        changed_fields=list(changes),
        reason=f"changed {', '.join(f'{k}={v}' for k, v in changes.items())}",
        **changes,  # type: ignore[arg-type]
    )


@pytest.fixture
def repo() -> _MemoryRepo:
    return _MemoryRepo()


@pytest.fixture
def service(repo: _MemoryRepo, test_settings: Settings) -> UserSettingsService:
    async def store(event: DomainEvent, key: str) -> str:
        data = {k: v for k, v in event.model_dump().items() if k in _event_fields}
        repo.events.append(DomainUserSettingsChangedEvent(**data))
        return event.event_id

    events = AsyncMock(spec=KafkaEventService)
    events.publish_event.side_effect = store
    return UserSettingsService(repo, events, test_settings, structlog.get_logger("test"))


async def test_restore_survives_a_rebuild_and_later_updates_still_apply(
    service: UserSettingsService, repo: _MemoryRepo
) -> None:
    start = datetime.now(timezone.utc) - timedelta(minutes=10)
    repo.events = [_changed(start, theme=Theme.DARK), _changed(start + timedelta(minutes=1), theme=Theme.LIGHT)]

    restored = await service.restore_settings_to_point("u1", start + timedelta(seconds=30))

    assert restored.theme == Theme.DARK
    assert (await service.get_user_settings_fresh("u1")).theme == Theme.DARK

    await service.update_theme("u1", Theme.LIGHT)
    assert (await service.get_user_settings_fresh("u1")).theme == Theme.LIGHT


async def test_history_returns_the_newest_events_newest_first(service: UserSettingsService, repo: _MemoryRepo) -> None:
    start = datetime.now(timezone.utc) - timedelta(minutes=10)
    repo.events = [_changed(start + timedelta(minutes=i), custom_settings={"n": i}) for i in range(5)]

    history = await service.get_settings_history("u1", limit=3)

    assert [entry.new_value for entry in history] == [{"n": 4}, {"n": 3}, {"n": 2}]
    assert [entry.timestamp for entry in history] == [start + timedelta(minutes=i) for i in (4, 3, 2)]
    assert {entry.field for entry in history} == {"/custom_settings"}
