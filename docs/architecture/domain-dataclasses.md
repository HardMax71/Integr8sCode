# Domain dataclasses

The stored entities are Beanie documents ([Model Conversion](model-conversion.md)), so the domain layer holds everything else: value objects embedded in documents, results, filters, configs, and the changes a partial update makes. Value objects and results are stdlib dataclasses, and update changes are `TypedDict`s. They live under `app/domain/` (plus `app/dlq/models.py`) and import nothing from Beanie or `app/db/docs`, since the documents import them. Pydantic stays at the edges: request and response schemas in `app/schemas_pydantic/`, documents in `app/db/docs/`, and the Kafka events in `app/domain/events/typed.py`, the one domain module that uses it.

No dataclass repeats the fields of a document. When a service needs an entity, it takes the document.

## What dataclasses don't do

A dataclass doesn't validate types and doesn't convert nested dicts. `ReplayConfig(filter={"user_id": "u1"}, max_events=10)` builds fine and leaves a dict where a `ReplayFilter` should be. So nothing builds a dataclass from a dict by unpacking it.

The opposite holds inside Pydantic models, and the code relies on that. When a dataclass is a field type of a `BaseModel` or a document, Pydantic validates it and converts dicts: `ExecutionDocument.resource_usage` is a `ResourceUsageDomain`, `ReplaySessionDocument.config` a `ReplayConfig` with its `ReplayFilter`, and `UserSettingsDocument` keeps its notification and editor settings as dataclasses. Those documents register `dataclasses.asdict` in `bson_encoders` so the values can be written to MongoDB. Where a dataclass has to come from a dict outside a model, a `TypeAdapter` validates it, the way the settings route builds `SystemSettings` from the request.

## Where they live

| File | Main types |
|---|---|
| `app/domain/user/user_models.py` | `UserChanges`, `UserDeleteResult`, `LoginResult` |
| `app/domain/user/settings_models.py` | `DomainNotificationSettings`, `DomainEditorSettings`, `UserSettingsChanges`, `DomainUserSettingsChangedEvent` |
| `app/domain/execution/models.py` | `ExecutionResultDomain`, `CancelResult`, `ResourceLimitsDomain` |
| `app/domain/replay/models.py` | `ReplayFilter`, `ReplayConfig`, `ReplayError` |
| `app/domain/events/event_models.py` | `EventFilter`, `EventListResult`, `EventStatistics` |
| `app/domain/events/typed.py` | `EventMetadata`, `ResourceUsageDomain` (next to the Pydantic events) |
| `app/domain/notification/models.py` | `NotificationChanges` |
| `app/domain/saved_script/models.py` | `SavedScriptChanges` |
| `app/domain/rate_limit/rate_limit_models.py` | `RateLimitConfig`, `RateLimitRule`, `UserRateLimit` |
| `app/domain/admin/settings_models.py` | `SystemSettings` |
| `app/domain/admin/replay_models.py` | `ReplaySessionData` |
| `app/domain/idempotency/models.py` | `IdempotencyRecord` |
| `app/domain/sse/models.py` | `SSEExecutionEventData` |
| `app/dlq/models.py` | `DLQMessageChanges`, `RetryPolicy` |

## Writing one

`ReplayConfig` in `app/domain/replay/models.py`, embedded in `ReplaySessionDocument.config`, shows the conventions for a value object:

```python
@dataclass
class ReplayConfig:
    """What a replay session sends again: the stored events that match the filter, up to max_events."""

    filter: ReplayFilter
    max_events: int
```

Mutable defaults and generated values use `field(default_factory=...)`. Timestamps are timezone-aware, from `datetime.now(timezone.utc)`. Generated ids use `default_factory=lambda: str(uuid4())`, so code never checks them for None. Enums are `StringEnum` subclasses.

A partial update's changes are a `TypedDict` with `total=False`. A key that's there gets set, and a key that isn't keeps the stored value:

```python
class SavedScriptChanges(TypedDict, total=False):
    """Fields an update sets; a missing key keeps the stored value and None clears the description."""

    name: str
    script: str
    lang: str
    lang_version: str
    description: str | None
```

A new value object embedded in a document needs the document's `bson_encoders` entry. Without it, writing the document fails with Beanie's "Cannot encode" `ValueError`.
