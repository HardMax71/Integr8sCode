# Domain dataclasses

This document explains how domain models use stdlib `dataclasses.dataclass` and how conversion between layers works.

## Why stdlib dataclasses

Domain models represent business entities like `DomainUserSettings`, `DomainExecution`, and `Saga`. They are pure Python
with no framework dependencies — just `from dataclasses import dataclass, field`.

This keeps the domain layer decoupled from Pydantic, Beanie, and other infrastructure. Services work with dataclasses
directly; conversion to/from Pydantic models and Beanie documents happens at layer boundaries (repositories, routes).

## What stdlib dataclasses provide

| Feature                | stdlib dataclass | Pydantic BaseModel |
|------------------------|------------------|--------------------|
| `asdict()`             | Yes              | No (`model_dump()`) |
| `is_dataclass()`       | Yes              | No                 |
| `__dataclass_fields__` | Yes              | No                 |
| `field()`              | Yes              | `Field()`          |
| `__post_init__`        | Yes              | `model_post_init`  |
| `replace()`            | Yes              | `model_copy()`     |
| frozen/eq/hash         | Yes              | Yes                |
| Inheritance            | Yes              | Yes                |
| Nested dict conversion | No               | Yes                |
| Type validation        | No               | Yes                |

Stdlib dataclasses do **not** validate types or auto-convert nested dicts. Repositories handle nested conversion
explicitly when loading from MongoDB. See [Model Conversion Patterns](model-conversion.md) for the conversion patterns.

## Domain model locations

All domain models live in `app/domain/` and use stdlib dataclasses:

| Module       | File                                  | Key models                                                                 |
|--------------|---------------------------------------|----------------------------------------------------------------------------|
| User         | `app/domain/user/settings_models.py`  | `DomainUserSettings`, `DomainNotificationSettings`, `DomainEditorSettings` |
| User         | `app/domain/user/user_models.py`      | `User`, `DomainUserCreate`, `DomainUserUpdate`                             |
| Execution    | `app/domain/execution/models.py`      | `DomainExecution`, `ExecutionResultDomain`                                 |
| Events       | `app/domain/events/event_models.py`   | `EventSummary`, `EventFilter`, `EventListResult`, `EventBrowseResult`      |
| Events       | `app/domain/events/typed.py`          | `EventMetadata`                                                            |
| Saga         | `app/domain/saga/models.py`           | `Saga`, `SagaContextData`                                                  |
| Replay       | `app/domain/replay/models.py`         | `ReplaySessionState`                                                       |
| Notification | `app/domain/notification/models.py`   | `DomainNotification`, `DomainNotificationSubscription`                     |
| Admin        | `app/domain/admin/settings_models.py` | `SystemSettings`, `ExecutionLimits`                                        |

## Using domain models in repositories

Repositories load from MongoDB and convert Beanie documents to domain models. Since stdlib dataclasses don't
auto-convert nested dicts, repositories handle nested objects explicitly:

```python
from dataclasses import asdict

class SagaRepository:
    def _to_domain(self, doc: SagaDocument) -> Saga:
        data = doc.model_dump(exclude={"id", "revision_id"})
        # Explicitly convert nested dataclass
        if ctx := data.get("context_data"):
            data["context_data"] = SagaContextData(**ctx)
        return Saga(**data)
```

For simpler models without nested dataclasses, constructor unpacking works directly:

```python
class UserSettingsRepository:
    async def get_snapshot(self, user_id: str) -> DomainUserSettings | None:
        doc = await UserSettingsDocument.find_one({"user_id": user_id})
        if not doc:
            return None
        return DomainUserSettings(**doc.model_dump(exclude={"id", "revision_id"}))
```

## What stays as Pydantic BaseModel

Some classes still use `pydantic.BaseModel` instead of dataclasses:

- Beanie documents (require BaseModel for ODM features)
- Request/response schemas in `app/schemas_pydantic/` (FastAPI integration)
- Kafka event payloads in `app/domain/events/typed.py` (FastStream serialization)
- Configuration models with complex validation

The rule: use stdlib dataclasses for domain models that represent business entities. Use BaseModel for infrastructure
concerns like documents, schemas, events, and configs.

## Adding new domain models

When creating a new domain model:

1. Import from stdlib: `from dataclasses import dataclass, field`
2. Define the class with `@dataclass` decorator
3. Use type annotations for documentation (no runtime validation)
4. Put nested dataclasses before the parent class that uses them

```python
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class NestedModel:
    value: int
    label: str = "default"

@dataclass
class ParentModel:
    id: str
    nested: NestedModel
    items: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
```

Remember: stdlib dataclasses don't validate input. If you pass a dict where `NestedModel` is expected, it stays as a
dict. Repositories must handle nested conversion explicitly.

## Related docs

- [User Settings Events](user-settings-events.md) — practical example of TypeAdapter usage for event sourcing
- [Model Conversion Patterns](model-conversion.md) — general patterns for converting between model types
