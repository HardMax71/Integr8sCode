# Domain exceptions

Services raise domain exceptions, and one handler turns them into HTTP responses. No route raises `HTTPException`. A service says `ExecutionNotFoundError(execution_id)` and never thinks about status codes, so the same code works from a route, a Kafka handler or a test.

## Base classes

Everything inherits from `DomainError` in `app/domain/exceptions.py`, which stores the text in `message`. The base class decides the status:

| Base class | Status | Meaning |
|------------|--------|---------|
| `NotFoundError` | 404 | entity doesn't exist; takes `entity` and `identifier` |
| `ValidationError` | 422 | business rule violated |
| `ThrottledError` | 429 | limit exceeded |
| `ConflictError` | 409 | duplicate or concurrent change |
| `UnauthorizedError` | 401 | not authenticated |
| `ForbiddenError` | 403 | authenticated but not allowed |
| `InvalidStateError` | 400 | operation not valid in the current state |
| `AccountLockedError` | 423 | too many failed logins |
| `InfrastructureError` | 500 | database, Kafka or Kubernetes failure |

A plain `DomainError` also maps to 500.

## Hierarchy

Each domain package defines its own subclasses in an `exceptions.py` and exports them from its `__init__.py`:

```text
DomainError
├── NotFoundError
│   ├── ExecutionNotFoundError        execution
│   ├── SagaNotFoundError             saga
│   ├── NotificationNotFoundError     notification
│   ├── SavedScriptNotFoundError      saved_script
│   ├── ReplaySessionNotFoundError    replay
│   ├── EventNotFoundError            events
│   └── UserNotFoundError             user
├── ValidationError
│   ├── RuntimeNotSupportedError      execution
│   └── NotificationValidationError   notification
├── ThrottledError
│   └── NotificationThrottledError    notification
├── ConflictError
│   └── SagaConcurrencyError          saga
├── UnauthorizedError
│   ├── AuthenticationRequiredError   user
│   └── InvalidCredentialsError       user
├── ForbiddenError
│   ├── ExecutionAccessDeniedError    execution
│   ├── SagaAccessDeniedError         saga
│   ├── AdminAccessRequiredError      user
│   ├── AccountDeactivatedError       user
│   └── CSRFValidationError           user
├── InvalidStateError
│   ├── ExecutionNotRetryableError    execution
│   ├── ExecutionTerminalError        execution
│   ├── SagaInvalidStateError         saga
│   └── SelfDeletionError             user
├── InfrastructureError
│   └── ReplayOperationError          replay
└── AccountLockedError
```

The right column is the package under `app/domain/`, so `EventNotFoundError` lives in `app/domain/events/exceptions.py`. A few of these have a status worth knowing. `RuntimeNotSupportedError` (422) rejects a language version that isn't offered, on execute, retry and saved scripts. `ExecutionNotRetryableError` (400) refuses to retry a queued or running execution, and `ExecutionTerminalError` (400) refuses to cancel a finished one. `SelfDeletionError` (400) stops an admin from deleting their own account.

`CSRFValidationError` never reaches the global handler: `CSRFMiddleware` catches it and answers 403 itself.

Subclasses that carry context take it in the constructor and keep it as attributes, so logs and tests can read `exc.saga_id` or `exc.limit` without parsing the message:

```python
--8<-- "backend/app/domain/saga/exceptions.py:SagaAccessDeniedError"
```

```python
--8<-- "backend/app/domain/notification/exceptions.py:NotificationThrottledError"
```

## Handler

`configure_exception_handlers` in `app/core/exceptions/handlers.py` registers the handlers that answer every error with the same `ErrorResponse`, a `DomainError` among them:

```python
--8<-- "backend/app/core/exceptions/handlers.py:configure_exception_handlers"
```

The body is `ErrorResponse(status, detail)` from `app/schemas_pydantic/common.py`, the `status` and `detail` members of RFC 9457 problem details. The same body comes back for FastAPI's own `HTTPException`s, for request validation errors (`detail` lists `field: message` pairs joined by `; `), for anything unexpected (a 500 with "Internal server error"; Starlette re-raises it afterwards, so the server still logs the traceback) and from the rate-limit, CSRF and request-size middlewares. `create_app` declares it as every route's `default` response, which also keeps FastAPI from documenting its own `HTTPValidationError`. Routes list the errors their services raise in `responses={...}` so they show up in the OpenAPI spec. The 401 and 403 from the `current_user` and `admin_user` dependencies mostly aren't listed, so the spec leaves them out.

## Where exceptions are raised

Repositories return `None` for a missing entity. They raise only when a write breaks a constraint: `UserRepository.create_user` raises `ConflictError` on a duplicate key, and `SagaRepository` raises `SagaConcurrencyError` on a revision mismatch and `SagaInvalidStateError` when cancelling a saga that is no longer active.

Services check for `None`, log, and raise the specific error. Trimmed from `SavedScriptService.get_saved_script`:

```python
script = await self.saved_script_repo.get_saved_script(script_id, user_id)
if not script:
    self.logger.warning("Script not found for user", user_id=user_id, script_id=script_id)
    raise SavedScriptNotFoundError(script_id)
return script
```

The route just calls the service and returns the schema. It has no `None` check and no `HTTPException`.

Kafka handlers in the worker raise the same exceptions, for example `ExecutionNotFoundError` in the result processor. No HTTP mapping applies there: the error goes up to FastStream, whose telemetry middleware records it under `error_type` on `messaging_process_duration_seconds`.

## Testing

Tests assert on the type and its fields instead of status codes. This one follows `tests/e2e/services/saga/test_saga_service.py`, which gets the service from the Dishka `scope` fixture and builds the caller with `make_test_user`:

```python
async def test_get_saga_not_found(scope: AsyncContainer) -> None:
    svc: SagaService = await scope.get(SagaService)
    with pytest.raises(SagaNotFoundError) as exc_info:
        await svc.get_saga_with_access_check("nonexistent-saga-id", make_test_user())
    assert exc_info.value.identifier == "nonexistent-saga-id"
```

## Adding one

Pick the base class for the status you want, put the class in the domain package's `exceptions.py`, export it from `__init__.py`, and raise it from the service. Give it a constructor if callers need the context. The handler maps it with no extra code:

```python
# app/domain/execution/exceptions.py
class ExecutionQuotaExceededError(ThrottledError):
    def __init__(self, user_id: str, current: int, limit: int) -> None:
        self.user_id = user_id
        self.current = current
        self.limit = limit
        super().__init__(f"Execution quota exceeded for user '{user_id}': {current}/{limit}")
```

This class is an example and doesn't exist in the code. Because it extends `ThrottledError`, it would come back as 429.
