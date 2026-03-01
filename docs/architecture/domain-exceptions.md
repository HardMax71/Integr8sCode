# Domain exceptions

This document explains how the backend handles errors using domain exceptions. It covers the exception hierarchy, how
services use them, and how the middleware maps them to HTTP responses.

## Why domain exceptions

Services used to throw `HTTPException` directly with status codes like 404 or 422. That worked but created tight
coupling between business logic and HTTP semantics. A service that throws `HTTPException(status_code=404)` knows it's
running behind an HTTP API, which breaks when you want to reuse that service from a CLI tool, a message consumer, or a
test harness.

Domain exceptions fix this by letting services speak in business terms. A service raises
`ExecutionNotFoundError(execution_id)` instead of `HTTPException(404, "Execution not found")`. The exception handler
middleware maps domain exceptions to HTTP responses in one place. Services stay transport-agnostic, tests assert on
meaningful exception types, and the mapping logic lives where it belongs.

## Exception hierarchy

All domain exceptions inherit from `DomainError`, which lives in `app/domain/exceptions.py`. The base classes map to
HTTP status codes:

| Base class            | HTTP status | Use case                             |
|-----------------------|-------------|--------------------------------------|
| `NotFoundError`       | 404         | Entity doesn't exist                 |
| `ValidationError`     | 422         | Invalid input or state               |
| `ThrottledError`      | 429         | Rate limit exceeded                  |
| `ConflictError`       | 409         | Concurrent modification or duplicate |
| `UnauthorizedError`   | 401         | Missing or invalid credentials       |
| `ForbiddenError`      | 403         | Authenticated but not allowed        |
| `InvalidStateError`   | 400         | Operation invalid for current state  |
| `InfrastructureError` | 500         | External system failure              |
| `AccountLockedError`  | 423         | Account temporarily locked           |

Each domain module defines specific exceptions that inherit from these bases. The hierarchy looks like this:

```
DomainError
├── NotFoundError
│   ├── ExecutionNotFoundError
│   ├── SagaNotFoundError
│   ├── NotificationNotFoundError
│   ├── SavedScriptNotFoundError
│   ├── ReplaySessionNotFoundError
│   └── UserNotFoundError
├── ValidationError
│   ├── RuntimeNotSupportedError
│   └── NotificationValidationError
├── ThrottledError
│   └── NotificationThrottledError
├── ConflictError
│   └── SagaConcurrencyError
├── UnauthorizedError
│   ├── AuthenticationRequiredError
│   ├── InvalidCredentialsError
│   └── TokenExpiredError
├── ForbiddenError
│   ├── SagaAccessDeniedError
│   ├── AdminAccessRequiredError
│   └── CSRFValidationError
├── InvalidStateError
│   └── SagaInvalidStateError
└── InfrastructureError
    ├── EventPublishError
    ├── SagaTimeoutError
    └── ReplayOperationError
```

## Exception locations

Domain exceptions live in their respective domain modules:

| Module       | File                                    | Exceptions                                                                                                                                            |
|--------------|-----------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| Base         | `app/domain/exceptions.py`              | `DomainError`, `NotFoundError`, `ValidationError`, etc.                                                                                               |
| Execution    | `app/domain/execution/exceptions.py`    | `ExecutionNotFoundError`, `RuntimeNotSupportedError`, `EventPublishError`                                                                             |
| Saga         | `app/domain/saga/exceptions.py`         | `SagaNotFoundError`, `SagaAccessDeniedError`, `SagaInvalidStateError`, `SagaTimeoutError`, `SagaConcurrencyError`                                     |
| Notification | `app/domain/notification/exceptions.py` | `NotificationNotFoundError`, `NotificationThrottledError`, `NotificationValidationError`                                                              |
| Saved Script | `app/domain/saved_script/exceptions.py` | `SavedScriptNotFoundError`                                                                                                                            |
| Replay       | `app/domain/replay/exceptions.py`       | `ReplaySessionNotFoundError`, `ReplayOperationError`                                                                                                  |
| User/Auth    | `app/domain/user/exceptions.py`         | `AuthenticationRequiredError`, `InvalidCredentialsError`, `TokenExpiredError`, `CSRFValidationError`, `AdminAccessRequiredError`, `UserNotFoundError` |

## Rich constructors

Specific exceptions have constructors that capture context for logging and debugging. Instead of just a message string,
they take structured arguments:

```python
--8<-- "backend/app/domain/saga/exceptions.py:SagaAccessDeniedError"
```

```python
--8<-- "backend/app/domain/notification/exceptions.py:NotificationThrottledError"
```

This means you can log `exc.saga_id` or `exc.limit` without parsing the message, and tests can assert on specific
fields.

## Exception handler

The middleware in `app/core/exceptions/handlers.py` catches all `DomainError` subclasses and maps them to JSON
responses:

```python
--8<-- "backend/app/core/exceptions/handlers.py:configure_exception_handlers"
```

The response includes the exception type name, so clients can distinguish between `ExecutionNotFoundError` and
`SagaNotFoundError` even though both return 404.

## Using exceptions in services

Services import exceptions from their domain module and raise them instead of `HTTPException`:

```python
# Before (coupled to HTTP)
from fastapi import HTTPException

async def get_execution(self, execution_id: str) -> DomainExecution:
    execution = await self.repo.get_execution(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution

# After (transport-agnostic)
from app.domain.execution import ExecutionNotFoundError

async def get_execution(self, execution_id: str) -> DomainExecution:
    execution = await self.repo.get_execution(execution_id)
    if not execution:
        raise ExecutionNotFoundError(execution_id)
    return execution
```

The service no longer knows about HTTP. It raises a domain exception that describes what went wrong in business terms.
The middleware handles the translation to HTTP.

## Testing with domain exceptions

Tests can assert on specific exception types and their fields:

```python
import pytest
from app.domain.saga import SagaNotFoundError, SagaAccessDeniedError

async def test_saga_not_found():
    with pytest.raises(SagaNotFoundError) as exc_info:
        await service.get_saga("nonexistent-id")
    assert exc_info.value.identifier == "nonexistent-id"

async def test_saga_access_denied():
    with pytest.raises(SagaAccessDeniedError) as exc_info:
        await service.get_saga_with_access_check(saga_id, unauthorized_user)
    assert exc_info.value.saga_id == saga_id
    assert exc_info.value.user_id == unauthorized_user.user_id
```

This is more precise than asserting on HTTP status codes and parsing error messages.

## Adding new exceptions

When adding a new exception:

1. Choose the right base class based on the HTTP status it should map to
2. Put it in the appropriate domain module's `exceptions.py`
3. Export it from the module's `__init__.py`
4. Use a rich constructor if the exception needs to carry context
5. Raise it from the service layer, not the API layer

Example for a new "quota exceeded" exception:

```python
# app/domain/execution/exceptions.py
from app.domain.exceptions import ThrottledError

class ExecutionQuotaExceededError(ThrottledError):
    def __init__(self, user_id: str, current: int, limit: int) -> None:
        self.user_id = user_id
        self.current = current
        self.limit = limit
        super().__init__(f"Execution quota exceeded for user '{user_id}': {current}/{limit}")
```

The handler automatically maps it to 429 because it inherits from `ThrottledError`.

## What stays as HTTPException

API routes can still use `HTTPException` for route-level concerns that don't belong in the service layer:

- Request validation that FastAPI doesn't catch (rare)
- Authentication checks in route dependencies
- Route-specific access control before calling services

The general rule: if it's about the business domain, use domain exceptions. If it's about HTTP mechanics at the route
level, `HTTPException` is fine.
