# Model Conversion Patterns

This document describes the patterns for converting between domain models, Pydantic schemas, and ODM documents.

## Core Principles

1. **Domain models are dataclasses** - pure Python, no framework dependencies
2. **Pydantic models are for boundaries** - API schemas, ODM documents, Kafka events
3. **No custom converter methods** - no `to_dict()`, `from_dict()`, `from_response()`, etc.
4. **Conversion at boundaries** - happens in repositories and services, not in models

## Model Layers

```
┌─────────────────────────────────────────────────────────────┐
│  API Layer (Pydantic schemas)                               │
│  app/schemas_pydantic/                                      │
├─────────────────────────────────────────────────────────────┤
│  Service Layer                                              │
│  app/services/                                              │
├─────────────────────────────────────────────────────────────┤
│  Domain Layer (dataclasses)                                 │
│  app/domain/                                                │
├─────────────────────────────────────────────────────────────┤
│  Infrastructure Layer (Pydantic/ODM)                        │
│  app/db/docs/, app/infrastructure/kafka/events/             │
└─────────────────────────────────────────────────────────────┘
```

## Conversion Patterns

### Dataclass to Dict

Use `asdict()` with dict comprehension for enum conversion and None filtering:

```python
from dataclasses import asdict

# With enum conversion and None filtering
update_dict = {
    k: (v.value if hasattr(v, "value") else v)
    for k, v in asdict(domain_obj).items()
    if v is not None
}

# Without None filtering (keep all values)
data = {
    k: (v.value if hasattr(v, "value") else v)
    for k, v in asdict(domain_obj).items()
}
```

### Pydantic to Dict

Use `model_dump()` directly:

```python
# Exclude None values
data = pydantic_obj.model_dump(exclude_none=True)

# Include all values
data = pydantic_obj.model_dump()

# JSON-compatible (datetimes as ISO strings)
data = pydantic_obj.model_dump(mode="json")
```

### Dict to Pydantic

Use `model_validate()` or constructor unpacking:

```python
# From dict
obj = SomeModel.model_validate(data)

# With unpacking
obj = SomeModel(**data)
```

### Pydantic to Pydantic

Use `model_validate()` when models have `from_attributes=True`:

```python
class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    ...

# Convert between compatible Pydantic models
user = User.model_validate(user_response)
```

### Dict to Dataclass

Use constructor unpacking:

```python
# Direct unpacking
domain_obj = DomainModel(**data)

# With nested conversion
domain_obj = DomainModel(
    **{
        **doc.model_dump(exclude={"id", "revision_id"}),
        "metadata": DomainMetadata(**doc.metadata.model_dump()),
    }
)
```

## Examples

### Repository: Saving Domain to Document

```python
async def store_event(self, event: Event) -> str:
    data = asdict(event)
    # Convert nested dataclass with enum handling
    data["metadata"] = {
        k: (v.value if hasattr(v, "value") else v)
        for k, v in asdict(event.metadata).items()
    }
    doc = EventDocument(**data)
    await doc.insert()
```

### Repository: Loading Document to Domain

```python
async def get_event(self, event_id: str) -> Event | None:
    doc = await EventDocument.find_one({"event_id": event_id})
    if not doc:
        return None
    return Event(
        **{
            **doc.model_dump(exclude={"id", "revision_id"}),
            "metadata": DomainMetadata(**doc.metadata.model_dump()),
        }
    )
```

### Repository: Updating with Typed Input

```python
async def update_session(self, session_id: str, updates: SessionUpdate) -> bool:
    update_dict = {
        k: (v.value if hasattr(v, "value") else v)
        for k, v in asdict(updates).items()
        if v is not None
    }
    if not update_dict:
        return False
    doc = await SessionDocument.find_one({"session_id": session_id})
    if not doc:
        return False
    await doc.set(update_dict)
    return True
```

### Service: Converting Between Pydantic Models

```python
# In API route
user = User.model_validate(current_user)

# In service converting Kafka metadata to domain
domain_metadata = DomainEventMetadata(**avro_metadata.model_dump())
```

## Anti-Patterns

### Don't: Custom Converter Methods

```python
# BAD - adds unnecessary abstraction
class MyModel:
    def to_dict(self) -> dict:
        return {...}

    @classmethod
    def from_dict(cls, data: dict) -> "MyModel":
        return cls(...)
```

### Don't: Pydantic in Domain Layer

```python
# BAD - domain should be framework-agnostic
from pydantic import BaseModel

class DomainEntity(BaseModel):  # Wrong!
    ...
```

### Don't: Manual Field-by-Field Conversion

```python
# BAD - verbose and error-prone
def from_response(cls, resp):
    return cls(
        field1=resp.field1,
        field2=resp.field2,
        field3=resp.field3,
        ...
    )
```

## Summary

| From | To | Method |
|------|-----|--------|
| Dataclass | Dict | `{k: (v.value if hasattr(v, "value") else v) for k, v in asdict(obj).items()}` |
| Pydantic | Dict | `obj.model_dump()` |
| Dict | Pydantic | `Model.model_validate(data)` or `Model(**data)` |
| Pydantic | Pydantic | `TargetModel.model_validate(source)` |
| Dict | Dataclass | `DataclassModel(**data)` |
