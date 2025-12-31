# User settings events

This document explains how user settings are stored, updated, and reconstructed using event sourcing with a unified event type and TypeAdapter-based merging.

## Unified event approach

All user settings changes emit a single `USER_SETTINGS_UPDATED` event type. There are no specialized events for theme, notifications, or editor settings. This eliminates branching in both publishing and consuming code.

```python
class UserSettingsUpdatedEvent(BaseEvent):
    event_type: Literal[EventType.USER_SETTINGS_UPDATED] = EventType.USER_SETTINGS_UPDATED
    topic: ClassVar[KafkaTopic] = KafkaTopic.USER_SETTINGS_EVENTS
    user_id: str
    changed_fields: list[str]
    changes: dict[str, str | int | bool | list | dict | None]
    reason: str | None = None
```

The `changed_fields` list identifies which settings changed. The `changes` dict contains the new values in JSON-serializable form (enums as strings, nested objects as dicts).

## Event payload structure

When updating settings, the service publishes:

```python
payload = {
    "user_id": "user_123",
    "changed_fields": ["theme", "notifications"],
    "changes": {
        "theme": "dark",
        "notifications": {
            "execution_completed": True,
            "channels": ["email", "in_app"]
        }
    },
    "reason": "User updated preferences"
}
```

No old values are tracked. If needed, previous state can be reconstructed by replaying events up to a specific timestamp.

## TypeAdapter pattern

The service uses Pydantic's `TypeAdapter` for dict-based operations without reflection or branching:

```python
from pydantic import TypeAdapter

_settings_adapter = TypeAdapter(DomainUserSettings)
_update_adapter = TypeAdapter(DomainUserSettingsUpdate)
```

### Updating settings

```python
async def update_user_settings(self, user_id: str, updates: DomainUserSettingsUpdate) -> DomainUserSettings:
    current = await self.get_user_settings(user_id)

    # Get only fields that were explicitly set
    changes = _update_adapter.dump_python(updates, exclude_none=True)
    if not changes:
        return current

    # Merge via dict unpacking
    current_dict = _settings_adapter.dump_python(current)
    merged = {**current_dict, **changes}
    merged["version"] = (current.version or 0) + 1
    merged["updated_at"] = datetime.now(timezone.utc)

    # Reconstruct with nested dataclass conversion
    new_settings = _settings_adapter.validate_python(merged)

    # Publish with JSON-serializable payload
    changes_json = _update_adapter.dump_python(updates, exclude_none=True, mode="json")
    await self._publish_settings_event(user_id, changes_json, reason)

    return new_settings
```

### Applying events

```python
def _apply_event(self, settings: DomainUserSettings, event: DomainSettingsEvent) -> DomainUserSettings:
    changes = event.payload.get("changes", {})
    if not changes:
        return settings

    current_dict = _settings_adapter.dump_python(settings)
    merged = {**current_dict, **changes}
    merged["updated_at"] = event.timestamp

    return _settings_adapter.validate_python(merged)
```

The `validate_python` call handles nested dict-to-dataclass conversion, enum parsing, and type coercion automatically. See [Pydantic Dataclasses](pydantic-dataclasses.md) for details.

## Settings reconstruction

User settings are rebuilt from a snapshot plus events:

```
┌─────────────────────────────────────────────────────────────┐
│  get_user_settings(user_id)                                 │
├─────────────────────────────────────────────────────────────┤
│  1. Check cache → return if hit                             │
│  2. Load snapshot from DB (if exists)                       │
│  3. Query events since snapshot.updated_at                  │
│  4. Apply each event via _apply_event()                     │
│  5. Cache result, return                                    │
└─────────────────────────────────────────────────────────────┘
```

Snapshots are created automatically when event count exceeds threshold:

```python
if (await self.repository.count_events_since_snapshot(user_id)) >= 10:
    await self.repository.create_snapshot(new_settings)
```

This bounds reconstruction cost while preserving full event history for auditing.

## Cache layer

Settings are cached with TTL to avoid repeated reconstruction:

```python
self._cache: TTLCache[str, DomainUserSettings] = TTLCache(
    maxsize=1000,
    ttl=timedelta(minutes=5).total_seconds(),
)
```

Cache invalidation happens via event bus subscription:

```python
async def initialize(self, event_bus_manager: EventBusManager) -> None:
    bus = await event_bus_manager.get_event_bus()

    async def _handle(evt: EventBusEvent) -> None:
        uid = evt.payload.get("user_id")
        if uid:
            await self.invalidate_cache(str(uid))

    await bus.subscribe("user.settings.updated*", _handle)
```

After each update, the service publishes to the event bus, triggering cache invalidation across instances.

## Settings history

The `get_settings_history` method returns a list of changes extracted from events:

```python
async def get_settings_history(self, user_id: str, limit: int = 50) -> List[DomainSettingsHistoryEntry]:
    events = await self._get_settings_events(user_id, limit=limit)
    history = []
    for event in events:
        changed_fields = event.payload.get("changed_fields", [])
        changes = event.payload.get("changes", {})
        for field in changed_fields:
            history.append(
                DomainSettingsHistoryEntry(
                    timestamp=event.timestamp,
                    event_type=event.event_type,
                    field=f"/{field}",
                    new_value=changes.get(field),
                    reason=event.payload.get("reason"),
                )
            )
    return history
```

## Key files

- `services/user_settings_service.py` — settings service with caching and event sourcing
- `domain/user/settings_models.py` — `DomainUserSettings`, `DomainUserSettingsUpdate` dataclasses
- `infrastructure/kafka/events/user.py` — `UserSettingsUpdatedEvent` definition
- `db/repositories/user_settings_repository.py` — snapshot and event queries
- `domain/enums/events.py` — `EventType.USER_SETTINGS_UPDATED`
