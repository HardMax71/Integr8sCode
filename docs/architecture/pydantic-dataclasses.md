# Pydantic dataclasses

This document explains why domain models use `pydantic.dataclasses.dataclass` instead of the standard library
`dataclasses.dataclass`. It covers the problem with nested dict conversion, the solution, and migration considerations.

## Why pydantic dataclasses

Domain models are dataclasses that represent business entities like `DomainUserSettings`, `DomainExecution`, and `Saga`.
These models often have nested structures - for example, `DomainUserSettings` contains `DomainNotificationSettings` and
`DomainEditorSettings` as nested dataclasses.

The problem appears when loading data from MongoDB. Beanie documents are Pydantic models, and calling `model_dump()` on
them returns plain Python dicts, including nested dicts for nested models. When you pass these dicts to a stdlib
dataclass constructor, nested dicts stay as dicts instead of being converted to their proper dataclass types.

```python
# Data from MongoDB via Beanie document.model_dump()
data = {
    "user_id": "user123",
    "notifications": {
        "execution_completed": False,
        "execution_failed": True
    }
}

# With stdlib dataclass - FAILS
settings = DomainUserSettings(**data)
settings.notifications.execution_completed  # AttributeError: 'dict' has no attribute 'execution_completed'

# With pydantic dataclass - WORKS
settings = DomainUserSettings(**data)
settings.notifications.execution_completed  # Returns False
```

Pydantic dataclasses use type annotations to automatically convert nested dicts into the correct dataclass instances. No
reflection, no isinstance checks, no manual conversion code.

## What pydantic dataclasses provide

Pydantic dataclasses are a drop-in replacement for stdlib dataclasses with added features:

| Feature                | stdlib | pydantic |
|------------------------|--------|----------|
| Nested dict conversion | No     | Yes      |
| Enum from string       | No     | Yes      |
| Type validation        | No     | Yes      |
| String-to-int coercion | No     | Yes      |
| `asdict()`             | Yes    | Yes      |
| `is_dataclass()`       | Yes    | Yes      |
| `__dataclass_fields__` | Yes    | Yes      |
| `field()`              | Yes    | Yes      |
| `__post_init__`        | Yes    | Yes      |
| `replace()`            | Yes    | Yes      |
| frozen/eq/hash         | Yes    | Yes      |
| Inheritance            | Yes    | Yes      |

The migration requires changing one import:

```python
# Before
from dataclasses import dataclass

# After
from pydantic.dataclasses import dataclass
```

Everything else stays the same. The `field` function still comes from stdlib `dataclasses`.

## Performance

Pydantic dataclasses add validation overhead at construction time:

| Operation          | stdlib      | pydantic    | Ratio       |
|--------------------|-------------|-------------|-------------|
| Creation from dict | 0.2 us      | 1.4 us      | 6x slower   |
| Attribute access   | 4.1 ms/100k | 4.6 ms/100k | 1.1x slower |

The creation overhead is negligible for typical usage patterns - domain models are created during request handling, not
in tight loops. Attribute access after construction has no meaningful overhead.

## Domain model locations

All domain models live in `app/domain/` and use pydantic dataclasses:

| Module       | File                                  | Key models                                                                 |
|--------------|---------------------------------------|----------------------------------------------------------------------------|
| User         | `app/domain/user/settings_models.py`  | `DomainUserSettings`, `DomainNotificationSettings`, `DomainEditorSettings` |
| User         | `app/domain/user/user_models.py`      | `User`, `UserCreation`, `UserUpdate`                                       |
| Execution    | `app/domain/execution/models.py`      | `DomainExecution`, `ExecutionResultDomain`                                 |
| Events       | `app/domain/events/event_models.py`   | `Event`, `EventFilter`, `EventQuery`                                       |
| Events       | `app/domain/events/event_metadata.py` | `EventMetadata`                                                            |
| Saga         | `app/domain/saga/models.py`           | `Saga`, `SagaInstance`, `SagaConfig`                                       |
| Replay       | `app/domain/replay/models.py`         | `ReplaySessionState`                                                       |
| Notification | `app/domain/notification/models.py`   | `DomainNotification`, `DomainNotificationSubscription`                     |
| Admin        | `app/domain/admin/settings_models.py` | `SystemSettings`, `ExecutionLimits`                                        |

## Using domain models in repositories

Repositories that load from MongoDB convert Beanie documents to domain models:

```python
from app.domain.user.settings_models import DomainUserSettings

class UserSettingsRepository:
    async def get_snapshot(self, user_id: str) -> DomainUserSettings | None:
        doc = await UserSettingsDocument.find_one({"user_id": user_id})
        if not doc:
            return None
        # Pydantic dataclass handles nested conversion automatically
        return DomainUserSettings(**doc.model_dump(exclude={"id", "revision_id"}))
```

No manual conversion of nested fields needed. The type annotations on `DomainUserSettings` tell pydantic how to convert
each nested dict.

## Validation behavior

Pydantic dataclasses validate input data at construction time. Invalid data raises `ValidationError`:

```python
# Invalid enum value
DomainUserSettings(user_id="u1", theme="invalid_theme")
# ValidationError: Input should be 'light', 'dark' or 'auto'

# Invalid type
DomainNotificationSettings(execution_completed="not_a_bool")
# ValidationError: Input should be a valid boolean
```

This catches data problems at the boundary where data enters the domain, rather than later during processing. Services
can trust that domain models contain valid data.

## What stays as Pydantic BaseModel

Some classes still use `pydantic.BaseModel` instead of dataclasses:

- Beanie documents (require BaseModel for ODM features)
- Request/response schemas (FastAPI integration)
- Configuration models with complex validation
- Classes that need `model_validate()`, `model_json_schema()`, or other BaseModel methods

The rule: use pydantic dataclasses for domain models that represent business entities. Use BaseModel for infrastructure
concerns like documents, schemas, and configs.

## Adding new domain models

When creating a new domain model:

1. Import dataclass from pydantic: `from pydantic.dataclasses import dataclass`
2. Import field from stdlib if needed: `from dataclasses import field`
3. Define the class with `@dataclass` decorator
4. Use type annotations - pydantic uses them for conversion and validation
5. Put nested dataclasses before the parent class that uses them

```python
from dataclasses import field
from datetime import datetime
from pydantic.dataclasses import dataclass

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

The model automatically handles nested dict conversion, enum parsing, and type coercion.

## Related docs

- [User Settings Events](user-settings-events.md) — practical example of TypeAdapter usage for event sourcing
- [Model Conversion Patterns](model-conversion.md) — general patterns for converting between model types
