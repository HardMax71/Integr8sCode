# Integr8sCode — Agent Instructions

Platform for running Python scripts online in isolated Kubernetes pods.
Users submit code through a Svelte 5 frontend → FastAPI backend → K8s pods.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Svelte 5 (runes), TypeScript strict, Rollup, TailwindCSS 4 |
| Backend | FastAPI, Dishka DI, Beanie ODM (MongoDB), Python 3.12, async throughout |
| Events | Kafka (KRaft, no ZooKeeper) + FastStream (Pydantic JSON) |
| Workers | k8s_worker, pod_monitor, result_processor, saga_orchestrator, dlq_processor, event_replay |
| Infra | MongoDB 8, Redis 7, optional Grafana / Jaeger / Victoria Metrics |

---

## Key Directory Map

```text
backend/app/
├── api/routes/         # FastAPI route handlers (DishkaRoute)
├── domain/             # Domain models (stdlib dataclasses), events, enums, exceptions
├── services/           # Business services — constructor-injected via Dishka
├── core/               # DI providers, middleware, utilities, container factories
├── events/             # Kafka handlers and consumers
└── db/                 # Beanie documents (db/docs/) and repositories (db/repositories/)

frontend/src/
├── routes/             # Page components
├── components/         # Reusable UI (admin/, editor/, ui/)
├── lib/api/            # Generated API client — DO NOT EDIT (run npm run generate:api)
├── lib/admin/          # Admin utilities: rate-limits/, sagas/, events/
├── stores/             # Auth, theme, notifications, user settings (.svelte.ts files)
└── styles/             # Global CSS
```

---

## Development Commands

```bash
# Backend (from backend/)
uv run pytest                                   # all tests
uv run pytest tests/unit/                       # unit only
uv run pytest -k "test_name" -x                 # single test, stop on failure
uv run ruff check . --config pyproject.toml     # lint (must pass)
uv run mypy --config-file pyproject.toml --strict .  # types (must pass)
uv run python scripts/check_orphan_modules.py   # dead code (must pass)

# Frontend (from frontend/)
npm run dev             # dev server with hot reload
npm run build           # production build
npm run check           # svelte-check — 0 errors, 0 warnings required
npm run lint            # ESLint
npm run test            # Vitest unit tests
npm run test:e2e        # Playwright E2E
npm run generate:api    # Regenerate API client after backend OpenAPI changes

# Full stack (from project root)
./deploy.sh dev --build          # rebuild and start
./deploy.sh dev --observability  # + Grafana, Jaeger, Victoria Metrics
./deploy.sh dev --wait           # start and wait for healthy
```

---

## Critical Architecture Rules

These layer boundaries are enforced throughout the codebase:

| Layer | Technology | Rule |
|-------|-----------|------|
| **Domain models** | stdlib `@dataclass` in `domain/` | Business logic — services use ONLY these |
| **Schema models** | Pydantic `BaseModel` in `schemas_pydantic/` | API boundary only (request/response) |
| **ODM models** | Beanie `Document` in `db/docs/` | Database layer only |

- Services never use schema models directly
- Routes convert: `SchemaResponse.model_validate(domain_result)` — `from_attributes=True` goes on the schema's `model_config`, never as a kwarg to `model_validate()`
- Repositories convert domain→document: `UserDocument(**dataclasses.asdict(create_data))`
- Repositories convert document→domain: `User(**doc.model_dump(include=_user_fields))`
- Nested dataclass fields must be converted explicitly in repositories (no automatic Pydantic coercion)

---

## Python Conventions

### Runtime & Tools
- Python **3.12+** — use modern syntax everywhere
- Always `uv run python`, never bare `python` or `python3`
- Max line length: **120 characters** (pyproject.toml)

### Type Hints (CRITICAL)

```python
# WRONG — never import these from typing
from typing import Optional, List, Dict, Union, Tuple, Set

# CORRECT — PEP 604 union syntax + PEP 585 built-in generics
def foo(x: str | None) -> list[dict[str, Any]]: ...
def bar(items: list[str], mapping: dict[str, int]) -> tuple[str, ...]: ...

# Allowed typing imports
from typing import TypeVar, Generic, Protocol, Callable, Any, TypeAlias, Literal, Annotated, TYPE_CHECKING
from collections.abc import Mapping, Sequence, Iterable, Iterator, Awaitable, Coroutine

# TypeAlias for complex types
UserId: TypeAlias = str
EventFilter: TypeAlias = list[EventType] | None
```

`StringEnum` subclasses are already `str` — no `.value` cast needed anywhere.
Use `NoReturn` return type for functions that always raise.

### Async/Await
- All I/O **must** be async — never `time.sleep()`, use `asyncio.sleep()`
- `async with` for context managers, `async for` for iteration

### Imports
- Absolute from package root: `from app.services.auth_service import AuthService`
- Relative imports only within same module directory
- Order: stdlib → third-party → local (blank line between each group)

### Code Style
- f-strings for all string formatting
- Early returns and guard clauses over nested conditions
- Docstrings: Google style (Args/Returns/Raises)
- **Never** use banner/separator comments (`# ---`, `# ===`, `# ***`)
- Use classes, blank lines, and docstrings to organize code

### Enums
Always inherit from `StringEnum` (`app.core.utils`):
```python
class UserRole(StringEnum):
    USER = "user"
    ADMIN = "admin"
```

### Logging
```python
# WRONG
import logging
logger = logging.getLogger(__name__)
logger.info("Event %s processed", event_id)

# CORRECT — inject structlog via DI, use keyword args
self.logger.info("Execution created", execution_id=exec_id, user_id=user_id)
self.logger.warning("Login failed", username=username, client_ip=ip, reason=reason)
```

Use `structlog.stdlib.BoundLogger` injected via Dishka constructor. Never call `logging.getLogger()` directly. Never interpolate user-controlled data into log messages — always pass as keyword args.

### Dataclasses vs Pydantic

| Use `@dataclass` for | Use Pydantic `BaseModel` for |
|----------------------|------------------------------|
| Domain models (pure business logic) | API request/response schemas |
| Internal DTOs | Kafka event payloads (FastStream) |
| Simple data containers without validation | ODM embedded sub-documents |

---

## Backend: Error Handling

### Exception Hierarchy (`app/domain/exceptions.py`)

```python
class DomainError(Exception):
    message: str  # base for all domain errors

class NotFoundError(DomainError):     # → HTTP 404; args: entity, identifier
class ValidationError(DomainError):   # → HTTP 422; business rule violations
class ConflictError(DomainError):     # → HTTP 409; duplicate, already exists
class ThrottledError(DomainError):    # → HTTP 429; rate limit exceeded
class UnauthorizedError(DomainError): # → HTTP 401; authentication required
class ForbiddenError(DomainError):    # → HTTP 403; authenticated but not permitted
class InvalidStateError(DomainError): # → HTTP 400; invalid state for operation
class AccountLockedError(DomainError):# → HTTP 423; too many failed login attempts
class InfrastructureError(DomainError):# → HTTP 500; DB, Kafka, K8s failures
```

Global exception handler in `app/core/exceptions/handlers.py` automatically maps all `DomainError` subclasses to HTTP status codes and returns `{"detail": exc.message, "type": "ClassName"}`.

**Rules:**
- Repositories return `T | None` for reads — **never raise `NotFoundError`**; raise only for write-constraint violations (e.g. `ConflictError` for a duplicate key)
- Services check `None` from the repo, log, and raise a domain-specific `NotFoundError` subclass — services never return `None` to route handlers
- Route handlers call the service and return the schema — they **never** raise `HTTPException` for domain-not-found cases; the global handler converts the exception to HTTP 404 automatically
- Use `raise SpecificError(...) from original_exc` to preserve exception chains
- Never catch `Exception` broadly; catch specific exception types

```python
# Repository — returns None for reads; raises only on write constraints
async def get_user(self, username: str) -> User | None:
    doc = await UserDocument.find_one(UserDocument.username == username)
    return User(**doc.model_dump(include=_user_fields)) if doc else None

async def create_user(self, data: UserCreate) -> User:
    doc = UserDocument(**dataclasses.asdict(data))
    try:
        await doc.insert()
    except DuplicateKeyError as e:
        raise ConflictError("User already exists") from e
    return User(**doc.model_dump(include=_user_fields))

# Service — checks None and raises domain exception (global handler → HTTP 404)
async def get_user(self, user_id: str) -> User:
    user = await self.user_repo.get_user_by_id(user_id)
    if not user:
        self.logger.warning("User not found", user_id=user_id)
        raise UserNotFoundError(user_id)
    return user

# Route — no None check, no HTTPException; service already raises if missing
@router.get("/{user_id}", response_model=UserResponse,
            responses={404: {"model": ErrorResponse}})
async def get_user(user_id: str, service: FromDishka[AdminUserService]) -> UserResponse:
    user = await service.get_user(user_id=user_id)
    return UserResponse.model_validate(user)
```

The API error response schema is `ErrorResponse(detail: str, type: str | None)` from `app/schemas_pydantic/common.py`.

---

## Backend: FastAPI Routes

```python
from typing import Annotated
from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, Header, Request

router = APIRouter(
    prefix="/admin/users",
    tags=["admin", "users"],
    route_class=DishkaRoute,           # enables automatic Dishka injection
    dependencies=[Depends(admin_user)],# router-level auth guard
)

@router.post(
    "/execute",
    response_model=ExecutionResponse,
    responses={
        409: {"model": ErrorResponse, "description": "Duplicate execution"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
)
async def create_execution(
    request: Request,
    current_user: Annotated[User, Depends(current_user)],
    execution: ExecutionRequest,          # Pydantic request body
    service: FromDishka[ExecutionService],# injected service
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ExecutionResponse:
    result = await service.execute_script(...)
    return ExecutionResponse.model_validate(result)
```

**Rules:**
- All routes in `app/api/routes/`, prefix `/api/v1/` via `settings.API_V1_STR`
- **Path ordering**: literal paths (`/defaults`) before parameterised (`/{user_id}`) in the same router
- Return Pydantic schema models, **never** raw dicts
- Use `responses={}` to document non-200 outcomes
- Auth: JWT via httpOnly cookie + CSRF double-submit (X-CSRF-Token header required for POST/PUT/DELETE)
- OpenAPI/docs disabled in production

---

## Backend: Dependency Injection (Dishka)

```python
from dishka import Provider, Scope, provide

class MyProvider(Provider):
    scope = Scope.REQUEST  # or Scope.APP for singletons

    @provide
    async def get_service(
        self,
        repo: UserRepository,
        producer: UnifiedProducer,
        logger: structlog.stdlib.BoundLogger,
        settings: Settings,
    ) -> MyService:
        return MyService(repo, producer, logger, settings)
```

- Providers in `app/core/providers/` modules
- `FromDishka[ServiceType]` in route handlers for injection
- `@inject` decorator when needed outside routes
- Container factories in `app/core/container.py` — one per worker type (`create_app_container`, `create_saga_container`, etc.)
- `setup_dishka(container, broker=broker, auto_inject=True)` called **after** subscriber registration, **before** broker start (workers only)
- Never instantiate services directly — always use DI

---

## Backend: Domain Models (Stdlib Dataclasses)

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

@dataclass
class DomainExecution:
    execution_id: str = field(default_factory=lambda: str(uuid4()))
    script: str = ""
    status: ExecutionStatus = ExecutionStatus.QUEUED
    user_id: str | None = None
    exit_code: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

- Pure Python — no Pydantic validation at construction
- `event_id` / UUID fields always use `default_factory` — never add None checks
- Nested dataclass fields: `context_data: SagaContextData = field(default_factory=SagaContextData)`
- Convert to dict: `dataclasses.asdict(domain_obj)` (for passing to ODM)
- Field set helper: `_user_fields = set(User.__dataclass_fields__)` for `model_dump(include=...)`

---

## Backend: Pydantic Schemas

```python
class UserResponse(BaseModel):
    user_id: str
    username: str
    role: UserRole
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_serialization_defaults_required=True,
    )
```

- Location: `app/schemas_pydantic/`
- `from_attributes=True` on model_config — never as kwarg to `model_validate()`
- `json_schema_serialization_defaults_required=True` for OpenAPI correctness
- Separate schemas: Create / Update / Response
- `ErrorResponse(detail: str, type: str | None)` — standard error shape

---

## Backend: Beanie ODM (MongoDB)

```python
from beanie import Document, Indexed
from pydantic import ConfigDict, Field

class UserDocument(Document):
    username: Indexed(str, unique=True)  # type: ignore[valid-type]
    email: Indexed(EmailStr, unique=True)  # type: ignore[valid-type]
    user_id: Indexed(str, unique=True) = Field(default_factory=lambda: str(uuid4()))  # type: ignore[valid-type]
    role: UserRole = UserRole.USER
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    class Settings:
        name = "users"
        use_state_management = True
```

- Documents in `app/db/docs/` — only top-level collection models extend `Document`
- Embedded sub-documents use plain `BaseModel` (no `EmbeddedDocument`)
- `Indexed(type, ...)` requires `# type: ignore[valid-type]` for mypy
- `arbitrary_types_allowed=True` required on Document models
- Compound indexes via `Settings.indexes = [IndexModel([...])]`
- Update pattern: `await doc.set({"field": value, "updated_at": now})`
- Atomic updates: `find_one().update(Set({...}), response_type=UpdateResponse.NEW_DOCUMENT)`

---

## Backend: Repository Pattern

```python
_user_fields = set(User.__dataclass_fields__)

class UserRepository:
    def __init__(self, logger: structlog.stdlib.BoundLogger) -> None:
        self.logger = logger

    async def get_user(self, username: str) -> User | None:
        doc = await UserDocument.find_one(UserDocument.username == username)
        return User(**doc.model_dump(include=_user_fields)) if doc else None

    async def create_user(self, data: UserCreate) -> User:
        doc = UserDocument(**dataclasses.asdict(data))
        try:
            await doc.insert()
        except DuplicateKeyError as e:
            raise ConflictError("User already exists") from e
        return User(**doc.model_dump(include=_user_fields))
```

- Location: `app/db/repositories/`
- Always return domain models, never ODM documents
- `doc.model_dump(include=_user_fields)` — filter to domain model fields only
- `dataclasses.asdict(domain)` — convert domain→document on write
- Inject `structlog.stdlib.BoundLogger` via constructor
- Raise domain exceptions for write-constraint violations only (e.g. `ConflictError` for a duplicate key) — **not** for missing entities; return `None` instead

---

## Backend: Services

```python
class ExecutionService:
    def __init__(
        self,
        execution_repo: ExecutionRepository,
        producer: UnifiedProducer,
        settings: Settings,
        logger: structlog.stdlib.BoundLogger,
        execution_metrics: ExecutionMetrics,
        idempotency_manager: IdempotencyManager,
    ) -> None:
        self.execution_repo = execution_repo
        self.producer = producer
        self.settings = settings
        self.logger = logger
        self.metrics = execution_metrics
        self.idempotency_manager = idempotency_manager
```

- Location: `app/services/`
- Constructor injection: repo, producer, logger, metrics, settings
- Record all significant operations: `self.metrics.record_*(…)`
- Publish events via `UnifiedProducer`: `await self.producer.produce(event, key=execution_id)`
- Services orchestrate domain logic — no direct DB or HTTP calls
- Always check `None` from repos and raise a domain-specific `NotFoundError` subclass (e.g. `ExecutionNotFoundError`, `SagaNotFoundError`) — never return `None` to a route

---

## Backend: Settings (TOML — No Env Vars)

```python
# WRONG — never use environment variables
DATABASE_URL = os.getenv("DATABASE_URL")

# CORRECT — inject via DI
settings: FromDishka[Settings]
```

Config load order (each overrides previous):
1. `config.toml` — base settings (committed)
2. `secrets.toml` — credentials (gitignored, never committed)
3. `config.<worker>.toml` — per-worker overrides (optional)

```python
Settings()                                           # config.toml + secrets.toml
Settings(config_path="config.test.toml")             # tests
Settings(override_path="config.saga-orchestrator.toml")  # worker
```

`Settings` uses `model_config = ConfigDict(extra="forbid")` — unknown keys are errors.

---

## Backend: Event System / Kafka

### Event Design
```python
class ExecutionRequestedEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_REQUESTED] = EventType.EXECUTION_REQUESTED
    execution_id: str
    script: str
    language: str
```

- All events extend `BaseEvent` (`app/domain/events/typed.py`)
- Discriminated union: `Annotated[..., Discriminator("event_type")]`
- `event_id` always has UUID from `default_factory` — never add None checks
- No `correlation_id` — use OpenTelemetry `trace_id`/`span_id` exclusively
- Events are immutable

### Kafka Topics
**1-topic-per-event-type** — topic name = `f"{prefix}{event_type}"` where `EventType IS a str` (no `.value` needed):
```python
# Producer (app/events/core/producer.py)
topic = f"{self._topic_prefix}{event_to_produce.event_type}"
await self.producer.produce(event_to_produce=event, key=execution_id)
```

### Consumers
```python
# One subscriber per handler — no shared topics, no filtering
@broker.subscriber("execution.requested", group_id="saga-orchestrator")
async def handle_execution_requested(event: ExecutionRequestedEvent) -> None:
    ...
```

- String literal `group_id` per consumer group
- One `@broker.subscriber(topic)` per handler — no multiplexing, no catch-alls

### Worker Pattern
```text
create container → init_beanie() → register handlers → start broker → run loop
```

Workers in `backend/workers/run_*.py`. Each uses a dedicated Dishka container.

| Worker | Purpose |
|--------|---------|
| k8s_worker | Creates/manages pods |
| pod_monitor | Watches pod lifecycle |
| result_processor | Stores execution results |
| saga_orchestrator | Distributed transactions + queue scheduling |
| dlq_processor | APScheduler-only (no Kafka consumer), retries failed messages |
| event_replay | Replays historical events |

---

## Frontend: Svelte 5 Runes (CRITICAL)

**Never use Svelte 4 patterns:** no `export let`, no `$:` reactive statements, no `writable()`/`readable()` stores in `.svelte` files.

```svelte
<script lang="ts">
    // Props — replaces `export let`
    interface Props {
        user: UserResponse;
        config: Config | null;
        onSave: () => void;
        children?: Snippet;           // for slot-like composition
    }
    let { user, config = $bindable(null), onSave, children }: Props = $props();

    // Local reactive state — replaces `let` reactivity
    let count = $state(0);
    let rawArray = $state.raw<Item[]>([]);   // non-deep reactive (better perf for lists)

    // Derived (memoized, no side effects)
    let doubled = $derived(count * 2);
    let computed = $derived.by(() => {       // multi-line derivation
        return expensiveCalc(count);
    });

    // Side effects with cleanup
    $effect(() => {
        const sub = subscribe(count);
        return () => sub.unsubscribe();      // cleanup function
    });
</script>

<!-- Render snippet -->
{@render children?.()}
```

### Shared / Global State
Use `.svelte.ts` files with ES6 classes (not plain objects):

```typescript
// stores/auth.svelte.ts
class AuthStore {
    isAuthenticated = $state<boolean | null>(null);
    username = $state<string | null>(null);
    csrfToken = $state<string | null>(null);

    async login(username: string, password: string): Promise<void> { ... }
    async logout(): Promise<void> { ... }
}
export const authStore = new AuthStore();
```

---

## Frontend: TypeScript

Strict mode + extra strictness enabled in `tsconfig.json`:
- `"strict": true`
- `"noUncheckedIndexedAccess": true` — array/object access returns `T | undefined`
- `"noImplicitReturns": true`
- `"verbatimModuleSyntax": true` — use `import type` for type-only imports

Path aliases (use always, never relative `../../lib/`):
```typescript
$lib        → src/lib
$components → src/components
$stores     → src/stores
$routes     → src/routes
$utils      → src/utils
```

Use `interface` for object shapes, `type` for unions/intersections/aliases. Define prop interfaces explicitly before `$props()`.

---

## Frontend: API Client

Generated from OpenAPI spec — **do not edit `src/lib/api/`**. Regenerate after backend changes:
```bash
# From project root
./deploy.sh openapi   # writes docs/reference/openapi.json; fails loudly on error
./deploy.sh types     # regenerates frontend/src/lib/api/ from the spec
```

Function names are derived from URL paths: `getUserRateLimitsApiV1AdminRateLimitsUserIdGet`.

```typescript
import { someApiEndpoint } from '$lib/api';
import { unwrap, unwrapOr } from '$lib/api-interceptors';

// unwrap — throws on error, use in event handlers (errors shown via interceptor toast)
const data = unwrap(await someApiEndpoint({ body: payload }));

// unwrapOr — returns fallback on error, use for optional/background loads
const data = unwrapOr(await someApiEndpoint({}), null);
```

---

## Frontend: Error Handling & API Interceptors

Global interceptor in `src/lib/api-interceptors.ts` handles:

| Status | Action |
|--------|--------|
| 401 | Clear auth, show "Session expired", redirect to `/login` |
| 403 | Toast error "Access denied." |
| 422 | Format validation errors, show as toast |
| 423 | Toast warning (account locked) |
| 429 | Toast warning "Too many requests. Please slow down." |
| 500+ | Toast error "Server error. Please try again later." |
| Network | Toast error "Network error. Check your connection." |

Auth endpoints (login/register) bypass error toasts. CSRF token (`X-CSRF-Token`) auto-injected on non-GET requests from `authStore.csrfToken`.

**Do not add try/catch around API calls** — interceptor handles display. Use `unwrap` / `unwrapOr` only.

---

## Frontend: Auth Store

- Auth state in `$stores/auth.svelte.ts` — session persisted to `sessionStorage`
- `verifyAuth()` — 30-second cache; returns cached state on network error (offline-first)
- `authStore.waitForInit()` — awaits one-time initialization before checking auth
- CSRF token attached to all non-GET requests automatically by interceptor
- `sessionStorage` key stores: `isAuthenticated`, `username`, `userId`, `userRole`, `csrfToken`

---

## Frontend: Routing

Uses `@mateothegreat/svelte5-router`. Routes defined in `App.svelte`:
```typescript
const requireAuth = async () => {
    await authStore.waitForInit();
    if (!authStore.isAuthenticated) {
        sessionStorage.setItem('redirectAfterLogin', window.location.pathname);
        goto('/login');
        return false;
    }
    return true;
};

{ path: "/editor", component: Editor, hooks: { pre: requireAuth } }
```

Navigation: `goto('/path')` programmatic, `route` directive on links.

---

## Testing

### Backend (pytest)

```text
backend/tests/
├── unit/        # No infra — fast
├── integration/ # Requires MongoDB, Redis, Kafka
└── e2e/         # Full stack — requires K8s (k3s in CI)
```

Markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.e2e`, `@pytest.mark.kafka`, `@pytest.mark.k8s`

All test functions are `async def`. Key fixtures: `test_settings`, `app`, `client`, `test_user`, `test_admin`.

**Test quality rules:**
- Test API responses precisely — status code **and** response body contents
- Use `@pytest.mark.parametrize` over duplicate test bodies
- Mock at service boundaries using `unittest.mock.AsyncMock`
- Prefer DI over `monkeypatch`/patching

```python
@pytest.mark.parametrize("client_fixture,expected_status,expected_detail", [
    ("test_user", 403, "Forbidden"),
    ("test_admin", 200, None),
])
async def test_admin_endpoint(request, client_fixture, expected_status, expected_detail):
    client = request.getfixturevalue(client_fixture)
    response = await client.get("/api/v1/admin/users/")
    assert response.status_code == expected_status
    if expected_detail:
        assert response.json()["detail"] == expected_detail
```

Isolation: `PYTEST_XDIST_WORKER` env var → separate Redis DB and MongoDB collections per parallel worker.

### Frontend (Vitest)

```typescript
// Always hoist mocks
const mocks = vi.hoisted(() => ({
    someApiFunction: vi.fn(),
}));

vi.mock('../../../lib/api', () => ({
    someApiFunction: (...args: unknown[]) => mocks.someApiFunction(...args),
}));
```

- Test colocated with source in `__tests__/` directories
- `cleanup()` in `afterEach`, `vi.clearAllMocks()` in `beforeEach`
- `await tick()` after render, `waitFor()` for async state
- Generated API client (`src/lib/api/`) excluded from coverage

### E2E (Playwright)
- Browser: Chromium only, base URL `https://localhost:5001`
- `ignoreHTTPSErrors: true` (self-signed certs), `timeout: 10000`, `expect.timeout: 3000`
- Seed test data: `docker compose exec -T backend uv run python scripts/seed_users.py`
- Test user: `user@test.com` / `user123`, Admin: `admin@test.com` / `admin123`

---

## CI Gates (All Must Pass)

```bash
# Backend
uv run ruff check . --config pyproject.toml        # rules: E, F, B, I, W; ignore W293
uv run mypy --config-file pyproject.toml --strict . # 318 source files
uv run python scripts/check_orphan_modules.py       # orphan module detection

# Frontend
npm run check   # svelte-check: 0 errors, 0 warnings
npm run test    # Vitest tests must pass
```

Grimp orphan module check (`backend/scripts/check_orphan_modules.py`) detects modules never imported by any other module in the package.

---

## Security Constraints

- K8s executor pods: non-root user, read-only filesystem, all capabilities dropped, `seccomp: RuntimeDefault`, `automountServiceAccountToken: false`
- NetworkPolicy: deny all ingress/egress for executor pods
- Passwords: bcrypt via passlib
- Login lockout after N failed attempts (configurable)
- Request size limit enforced via ASGI middleware (streams body, rejects before full payload enters memory; default 10MB)
- Rate limiting: per-user Redis-backed sliding window / token bucket; default groups: execution 10/60s, auth 20/60s, admin 100/60s
- CSRF: double-submit cookie pattern — `access_token` (httpOnly) + `csrf_token` (readable) + `X-CSRF-Token` header required for POST/PUT/DELETE
- Sensitive data (API keys, tokens, passwords) sanitized before logging
- Never log user-controlled data via string interpolation — always use structured keyword args
