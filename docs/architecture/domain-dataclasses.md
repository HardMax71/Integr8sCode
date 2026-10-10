# Domain dataclasses

Domain models are stdlib dataclasses, and they're what services work with. They live under `app/domain/` (plus `app/dlq/models.py`) and import nothing from Pydantic or Beanie. Pydantic stays at the edges: request and response schemas in `app/schemas_pydantic/`, Beanie documents in `app/db/docs/`, and the Kafka events in `app/domain/events/typed.py`, the one domain module that uses it.

## What dataclasses don't do

A dataclass doesn't validate types and doesn't convert nested dicts. `DomainUserSettings(notifications={"execution_failed": False})` builds fine and leaves a dict where a `DomainNotificationSettings` should be. `dataclasses.asdict()` recurses into nested dataclasses on the way out, but nothing reverses it on the way in. So whoever builds a dataclass from a dict converts the nested fields first. In practice that's the repositories, and [Model Conversion](model-conversion.md) shows how.

The opposite holds inside Pydantic models. When a dataclass is a field type of a `BaseModel`, Pydantic validates it and converts dicts. Events rely on that for `EventMetadata` and `ResourceUsageDomain`. Some Beanie documents use domain dataclasses as field types too: `EventDocument.metadata` is an `EventMetadata`, and `ReplaySessionDocument` keeps a `ReplayFilter` in its embedded config and a list of `ReplayError`. Those documents register `dataclasses.asdict` in `bson_encoders` so the values can be written to MongoDB.

## Where they live

| File | Main models |
|---|---|
| `app/domain/user/user_models.py` | `User`, `DomainUserCreate`, `DomainUserUpdate` |
| `app/domain/user/settings_models.py` | `DomainUserSettings`, `DomainNotificationSettings`, `DomainEditorSettings`, `DomainUserSettingsUpdate` |
| `app/domain/execution/models.py` | `DomainExecution`, `DomainExecutionCreate`, `ExecutionResultDomain` |
| `app/domain/saga/models.py` | `Saga`, `SagaContextData`, `SagaFilter`, `DomainResourceAllocation` |
| `app/domain/replay/models.py` | `ReplayFilter`, `ReplayConfig`, `ReplaySessionState` |
| `app/domain/events/event_models.py` | `EventFilter`, `EventListResult`, `EventStatistics` |
| `app/domain/events/typed.py` | `EventMetadata`, `ResourceUsageDomain` (next to the Pydantic events) |
| `app/domain/notification/models.py` | `DomainNotification`, `DomainNotificationSubscription` |
| `app/domain/saved_script/models.py` | `DomainSavedScript`, `DomainSavedScriptCreate`, `DomainSavedScriptUpdate` |
| `app/domain/rate_limit/rate_limit_models.py` | `RateLimitConfig`, `RateLimitRule`, `UserRateLimit` |
| `app/domain/admin/settings_models.py` | `SystemSettings` |
| `app/domain/sse/models.py` | `SSEExecutionEventData` |
| `app/dlq/models.py` | `DLQMessage`, `RetryPolicy` |

## Writing one

`Saga` in `app/domain/saga/models.py` shows the conventions:

```python
@dataclass
class Saga:
    """Domain model for saga."""

    saga_id: str
    saga_name: str
    execution_id: str
    state: SagaState
    current_step: str | None = None
    completed_steps: list[str] = field(default_factory=list)
    compensated_steps: list[str] = field(default_factory=list)
    context_data: SagaContextData = field(default_factory=SagaContextData)
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    retry_count: int = 0
```

Mutable defaults and nested dataclasses use `field(default_factory=...)`. Timestamps are timezone-aware, from `datetime.now(timezone.utc)`. Generated ids use `default_factory=lambda: str(uuid4())`, so code never checks them for None. Enums are `StringEnum` subclasses. The nested class (`SagaContextData`) is defined above the class that uses it.

Its repository rebuilds the nested field when loading:

```python
@staticmethod
def _to_domain(doc: SagaDocument) -> Saga:
    return Saga(
        **(d := doc.model_dump(include=_saga_fields)) | {"context_data": SagaContextData(**d["context_data"])}
    )
```

A new model with a nested dataclass needs the same treatment in its repository. Without it, the service gets a dict and fails later, far from the cause.
