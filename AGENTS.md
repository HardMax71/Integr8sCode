# Integr8sCode: Agent Instructions

Platform for running scripts online in isolated Kubernetes pods. Users write Python, Node.js, Ruby, Bash or Go in a Svelte 5 frontend, the FastAPI backend publishes the request to Kafka, and workers run it in its own pod.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Svelte 5 (runes), SvelteKit 3 (adapter-static SPA) on Vite 8, TanStack Query 6, TanStack Table 9, bits-ui 2, superforms 3 with formsnap, mode-watcher, TypeScript 6 strict, TailwindCSS 4, Node 26 |
| Backend | FastAPI, Dishka DI, Beanie ODM (MongoDB), Python 3.14 (backend/.python-version), async throughout, httpx2 for HTTP |
| Events | Kafka (KRaft, no ZooKeeper) + FastStream (Pydantic JSON) |
| Workers | k8s_worker, pod_monitor, result_processor, saga_orchestrator, dlq_processor, event_replay |
| Infra | MongoDB 9, Redis 8; optional Grafana, Jaeger, Victoria Metrics, Loki, OTel Collector (`--observability`) and Kafdrop (`--debug`) |
| Runtimes | Python 3.11 to 3.14, Node 22/24/26, Ruby 3.3/3.4/4.0, Bash 5.3, Go 1.26/1.27 (app/runtime_registry.py) |

## Key Directory Map

```text
backend/
├── app/
│   ├── api/routes/          # FastAPI route handlers (DishkaRoute), admin/ for admin routers
│   ├── core/                # providers.py (all Dishka providers), container.py, middlewares/, metrics/,
│   │                        # tracing/, exceptions/, security.py, logging.py, utils.py (StringEnum)
│   ├── db/                  # Beanie documents (db/docs/) and repositories (db/repositories/)
│   ├── dlq/                 # DLQ manager and models
│   ├── domain/              # Domain models (stdlib dataclasses), events, enums, exceptions
│   ├── events/              # handlers.py (Kafka routers), middlewares.py (idempotency), core/ (producer, transport)
│   ├── infrastructure/      # kafka/topics.py: event type groupings
│   ├── schemas_pydantic/    # API request and response schemas
│   ├── services/            # Business services, constructor-injected via Dishka
│   ├── scripts/             # entrypoint.sh mounted into executor pods
│   ├── main.py              # create_app()
│   ├── runtime_registry.py  # Languages, versions, images, per-language pod settings
│   └── settings.py          # Settings: TOML plus secrets from env
├── workers/                 # run_<worker>.py entry points, one per worker
├── scripts/                 # check_orphan_modules.py, seed_users.py
└── tests/                   # unit/, e2e/, contract/, load/

frontend/
├── e2e/                     # Playwright specs and fixtures.ts
├── static/                  # favicon, robots.txt, sitemap.xml, copied into the build as is
├── vite.config.ts           # SvelteKit plugin (adapter-static, CSP), Tailwind, dev server
└── src/
    ├── app.html             # Page template
    ├── hooks.client.ts      # init (API interceptors) and handleError
    ├── routes/              # SvelteKit routes: +page.svelte per page, (auth)/ and admin/ guarded by +layout.ts
    ├── components/          # Reusable UI: admin/, editor/, plus shared top-level components
    ├── lib/api/             # Generated API client, never edited by hand (see Frontend: API Client)
    ├── lib/admin/           # Admin utilities: events/, rate-limits/, sagas/
    ├── lib/editor/          # Execution state, the open script (draft), CodeMirror languages
    ├── lib/notifications/   # Notification SSE stream
    ├── lib/auth-guard.ts    # requireAuth and requireAdmin for the layout guards
    ├── lib/query-client.ts  # the one TanStack Query client, provided by the root layout
    ├── stores/              # auth, theme (a mode-watcher adapter); server data lives in the query cache
    └── styles/              # Global CSS
```

## Development Commands

```bash
# Backend (from backend/)
uv sync                                              # install deps (dev group: test, lint, load)
uv run pytest tests/unit                             # unit tests, no infra needed
uv run pytest tests/unit -k "test_name" -x           # single test, stop on first failure
uv run ruff check . --config pyproject.toml          # lint, tests included (must pass)
uv run mypy --config-file pyproject.toml --strict .  # types (must pass)
uv run python -m scripts.check_orphan_modules        # dead code (must pass)

# Frontend (from frontend/)
npm ci                    # install deps
npm run dev               # Vite dev server with HMR on :5001 (see note below)
npm run build             # production build
npm run check             # svelte-check, 0 errors and 0 warnings required
npm run lint              # ESLint
npm run stylelint         # Stylelint
npm run format:check      # Prettier
npm run test              # Vitest unit tests
npm run test:e2e:deps     # once: Playwright system deps for Chromium
npm run test:e2e:browsers # once: Playwright Chromium
npm run test:e2e          # Playwright E2E, needs the running stack

# Full stack (from project root)
./deploy.sh dev                  # start
./deploy.sh dev --build          # rebuild and start
./deploy.sh dev --wait           # start and wait for healthy
./deploy.sh dev --observability  # plus Grafana, Jaeger, Victoria Metrics, Loki, OTel Collector
./deploy.sh dev --debug          # observability plus Kafdrop
./deploy.sh down                 # stop
./deploy.sh openapi              # regenerate docs/reference/openapi.json
./deploy.sh types                # regenerate frontend/src/lib/api/ from that spec
```

`npm run dev` serves HTTPS when ./certs/server.key and server.crt exist and proxies /api to `https://backend:443`, a hostname that only resolves inside the compose network, so on the host the API calls fail. The compose `frontend` service already serves a production build on :5001; rebuild it with `./deploy.sh dev --build` after frontend changes.

Plain `uv run pytest` also collects tests/e2e, which needs the full stack, so always pass a path. E2E tests run inside the backend container against a running stack, the way CI does it (CI copies config.test.toml over config.toml before starting the stack):

```bash
docker compose exec -T backend sh -c 'uv sync --group test --no-dev --frozen --no-install-project && pytest tests/e2e'
```

## Critical Architecture Rules

These layer boundaries hold throughout the codebase:

| Layer | Technology | Rule |
|-------|-----------|------|
| Domain models | stdlib `@dataclass` in `domain/` | Business logic. Services use ONLY these |
| Schema models | Pydantic `BaseModel` in `schemas_pydantic/` | API boundary only (request/response) |
| ODM models | Beanie `Document` in `db/docs/` | Database layer only |

- Services never use schema models directly
- Routes convert with `SchemaResponse.model_validate(domain_result)`; `from_attributes=True` goes on the schema's `model_config`, never as a kwarg to `model_validate()`
- Repositories convert domain to document: `UserDocument(**dataclasses.asdict(create_data))`
- Repositories convert document to domain: `User(**doc.model_dump(include=_user_fields))`
- Nested dataclass fields must be converted explicitly in repositories (no automatic Pydantic coercion)

## Python Conventions

### Runtime & Tools
- Python **3.14** (backend/.python-version, `requires-python = ">=3.14"`); use modern syntax everywhere
- Always `uv run python`, never bare `python` or `python3`
- Max line length: 120 characters (pyproject.toml)
- HTTP client is `httpx2` (Pydantic's fork of httpx) in app code and tests. Never add `httpx` back

### Type Hints (CRITICAL)

```python
# WRONG: never import these from typing
from typing import Optional, List, Dict, Union, Tuple, Set, TypeAlias

# CORRECT: PEP 604 unions, PEP 585 built-in generics, PEP 695 aliases and generics
def foo(x: str | None) -> list[dict[str, Any]]: ...
def bar(items: list[str], mapping: dict[str, int]) -> tuple[str, ...]: ...

type UserId = str
type EventFilter = list[EventType] | None

def first[T](items: Sequence[T]) -> T | None: ...

# Allowed imports
from typing import Any, Annotated, Literal, NoReturn, NamedTuple, TypedDict, NotRequired, Protocol, TYPE_CHECKING
from collections.abc import Callable, Mapping, Sequence, Iterable, Iterator, Awaitable, AsyncIterator, AsyncGenerator
```

`StringEnum` subclasses are already `str`, so no `.value` cast is needed anywhere. Use `NoReturn` as the return type for functions that always raise.

### Async/Await
- All I/O must be async: never `time.sleep()`, use `asyncio.sleep()`
- `async with` for context managers, `async for` for iteration

### Imports
- Absolute from package root: `from app.services.auth_service import AuthService`
- Relative imports only within the same module directory
- Order: stdlib, third-party, local, with a blank line between groups (ruff `I` enforces it)

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

A member is named after its value (`SYSTEM = "system"`, never `AUTO = "system"`), so code and API use the same word; tests/unit/app/test_one_name.py checks every enum.

### Logging
```python
# WRONG
import logging
logger = logging.getLogger(__name__)
logger.info("Event %s processed", event_id)

# CORRECT: structlog injected via DI, keyword args
self.logger.info("Execution created", execution_id=exec_id, user_id=user_id)
self.logger.warning("Login failed", username=username, client_ip=ip, reason=reason)
```

Use `structlog.stdlib.BoundLogger` injected via the Dishka constructor. Never call `logging.getLogger()` directly. Never interpolate user-controlled data into log messages; always pass it as keyword args.

### Dataclasses vs Pydantic

| Use `@dataclass` for | Use Pydantic `BaseModel` for |
|----------------------|------------------------------|
| Domain models (pure business logic) | API request/response schemas |
| Internal DTOs | Kafka event payloads (FastStream) |
| Simple data containers without validation | ODM embedded sub-documents |

## Backend: Error Handling

### Exception Hierarchy (`app/domain/exceptions.py`)

```python
class DomainError(Exception):
    message: str  # base for all domain errors

class NotFoundError(DomainError):      # HTTP 404; args: entity, identifier
class ValidationError(DomainError):    # HTTP 422; business rule violations
class ConflictError(DomainError):      # HTTP 409; duplicate, already exists
class ThrottledError(DomainError):     # HTTP 429; rate limit exceeded
class UnauthorizedError(DomainError):  # HTTP 401; authentication required
class ForbiddenError(DomainError):     # HTTP 403; authenticated but not permitted
class InvalidStateError(DomainError):  # HTTP 400; invalid state for operation
class AccountLockedError(DomainError): # HTTP 423; too many failed login attempts
class InfrastructureError(DomainError):# HTTP 500; DB, Kafka, K8s failures
```

The global handler in `app/core/exceptions/handlers.py` maps every `DomainError` subclass to its HTTP status and returns `{"detail": exc.message, "type": "ClassName"}`.

Rules:
- Repositories return `T | None` for reads and **never raise `NotFoundError`**; they raise only for write-constraint violations (e.g. `ConflictError` for a duplicate key)
- Services check `None` from the repo, log, and raise a domain-specific `NotFoundError` subclass; services never return `None` to route handlers
- Route handlers call the service and return the schema. They **never** raise `HTTPException` for domain-not-found cases; the global handler turns the exception into a 404
- Use `raise SpecificError(...) from original_exc` to preserve exception chains
- Never catch `Exception` broadly; catch specific exception types (the two allowed cases follow)

A catch-all is allowed in two cases only. The first records or logs, then re-raises: `UnifiedProducer.produce` in `app/events/core/producer.py` marks the event as failed to publish, `IdempotencyMiddleware` and `DeadLetterMiddleware` in `app/events/middlewares.py` release the idempotency key and save the event to the DLQ, and `ExecutionService` marks the execution as errored before raising `InfrastructureError`. The second is a loop or batch boundary that must survive one bad item: the saga orchestrator's queue loop (`try_schedule_from_queue`), saga step execution and its compensation loop, the pod monitor's watch cycle (`workers/run_pod_monitor.py`) and per-event processing, k8s worker pod creation (publishes a pod-creation-failed event instead), notification delivery and the scheduled-notification batch, DLQ batch retry and per-event replay. A new catch-all needs the same justification and must log or record the error; never swallow it silently.

```python
# Repository: returns None for reads; raises only on write constraints
async def get_user(self, username: str) -> User | None:
    doc = await UserDocument.find_one(UserDocument.username == username)
    return User(**doc.model_dump(include=_user_fields)) if doc else None

async def create_user(self, create_data: DomainUserCreate) -> User:
    doc = UserDocument(**dataclasses.asdict(create_data))
    try:
        await doc.insert()
    except DuplicateKeyError as e:
        raise ConflictError("User already exists") from e
    return User(**doc.model_dump(include=_user_fields))

# Service: checks None and raises a domain exception (global handler returns 404)
async def get_user(self, user_id: str) -> User:
    user = await self.user_repo.get_user_by_id(user_id)
    if not user:
        self.logger.warning("User not found", user_id=user_id)
        raise UserNotFoundError(user_id)
    return user

# Route: no None check, no HTTPException; the service already raises if missing
@router.get("/{user_id}", response_model=UserResponse,
            responses={404: {"model": ErrorResponse}})
async def get_user(user_id: str, service: FromDishka[AdminUserService]) -> UserResponse:
    user = await service.get_user(user_id=user_id)
    return UserResponse.model_validate(user)
```

The API error response schema is `ErrorResponse(detail: str, type: str | None)` from `app/schemas_pydantic/common.py`.

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

Rules:
- All routes live in `app/api/routes/`, prefixed with `/api/v1` via `settings.API_V1_STR`
- Path ordering: literal paths (`/defaults`) before parameterised ones (`/{user_id}`) in the same router
- Return Pydantic schema models, **never** raw dicts
- Use `responses={}` to document non-200 outcomes
- Auth: JWT in an httpOnly cookie plus CSRF double-submit (`X-CSRF-Token` header required for POST, PUT, PATCH and DELETE)
- OpenAPI and docs pages are served only when `DEVELOPMENT_MODE` is true

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

- All providers live in one file, `app/core/providers.py`
- Container factories live in `app/core/container.py`, one per process: `create_app_container`, `create_k8s_worker_container`, `create_pod_monitor_container`, `create_result_processor_container`, `create_saga_orchestrator_container`, `create_event_replay_container`, `create_dlq_processor_container`
- `FromDishka[ServiceType]` injects into route handlers (`dishka.integrations.fastapi`) and Kafka subscribers (`dishka_faststream`)
- `@inject` decorator when needed outside routes (e.g. the `admin_user` dependency)
- `setup_dishka(container, broker=broker, auto_inject=True)` from `dishka_faststream` runs **after** subscriber registration and **before** the broker starts, in workers and in the API lifespan
- Never instantiate services directly; always use DI

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

- Pure Python, no Pydantic validation at construction
- `event_id` and other UUID fields always use `default_factory`; never add None checks
- Nested dataclass fields: `context_data: SagaContextData = field(default_factory=SagaContextData)`
- Convert to dict: `dataclasses.asdict(domain_obj)` (for passing to ODM)
- Field set helper: `_user_fields = set(User.__dataclass_fields__)` for `model_dump(include=...)`

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
- `from_attributes=True` on model_config, never as a kwarg to `model_validate()`
- `json_schema_serialization_defaults_required=True` for OpenAPI correctness
- Separate schemas: Create / Update / Response
- A field's key is its only name: no `alias`, `validation_alias`, `serialization_alias`, alias generator or custom `title`, since the frontend labels every field from its key (tests/unit/app/test_one_name.py)
- `ErrorResponse(detail: str, type: str | None)` is the standard error shape

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

- Documents in `app/db/docs/`; only top-level collection models extend `Document`
- Embedded sub-documents use plain `BaseModel` (no `EmbeddedDocument`)
- `Indexed(type, ...)` requires `# type: ignore[valid-type]` for mypy
- `arbitrary_types_allowed=True` required on Document models
- Compound indexes via `Settings.indexes = [IndexModel([...])]`
- Update pattern: `await doc.set({"field": value, "updated_at": now})`
- Atomic updates: `find_one().update(Set({...}), response_type=UpdateResponse.NEW_DOCUMENT)`

## Backend: Repository Pattern

```python
_user_fields = set(User.__dataclass_fields__)

class UserRepository:
    def __init__(self, logger: structlog.stdlib.BoundLogger) -> None:
        self.logger = logger

    async def get_user(self, username: str) -> User | None:
        doc = await UserDocument.find_one(UserDocument.username == username)
        return User(**doc.model_dump(include=_user_fields)) if doc else None

    async def create_user(self, create_data: DomainUserCreate) -> User:
        doc = UserDocument(**dataclasses.asdict(create_data))
        try:
            await doc.insert()
        except DuplicateKeyError as e:
            raise ConflictError("User already exists") from e
        return User(**doc.model_dump(include=_user_fields))
```

- Location: `app/db/repositories/`
- Always return domain models, never ODM documents
- `doc.model_dump(include=_user_fields)` filters to domain model fields
- `dataclasses.asdict(domain)` converts domain to document on write
- Inject `structlog.stdlib.BoundLogger` via constructor
- Raise domain exceptions for write-constraint violations only (e.g. `ConflictError` for a duplicate key), **not** for missing entities; return `None` instead

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
        runtime_settings: RuntimeSettingsLoader,
    ) -> None:
        self.execution_repo = execution_repo
        self.producer = producer
        self.settings = settings
        self.logger = logger
        self.metrics = execution_metrics
        self.idempotency_manager = idempotency_manager
        self._runtime_settings = runtime_settings
```

- Location: `app/services/`
- Constructor injection: repo, producer, logger, metrics, settings
- Record all significant operations: `self.metrics.record_*(...)`
- Publish events via `UnifiedProducer`: `await self.producer.produce(event_to_produce=event, key=execution_id)`
- Services orchestrate domain logic; no direct DB or HTTP calls
- Always check `None` from repos and raise a domain-specific `NotFoundError` subclass (e.g. `ExecutionNotFoundError`, `SagaNotFoundError`); never return `None` to a route

## Backend: Runtime Registry

`app/runtime_registry.py` is the one place that defines languages and versions.

- `LANGUAGE_SPECS` lists each language's versions newest first, plus image template, file extension and interpreter. A unit test enforces the order
- `DEFAULT_LANG` ("python") and `DEFAULT_LANG_VERSION` (the first python version, currently 3.14) are the only defaults. Every `lang` and `lang_version` default in schemas, domain models, documents and `ExecutionService` reads them, and a test pins that. Never hardcode a version
- `Settings.SUPPORTED_RUNTIMES` and `ExecutionRequest` validation both derive from `LANGUAGE_SPECS`. Removing a version makes new executions, retries and saved-script writes on it fail with 422; stored scripts still load
- Per-language pod settings go in the spec's optional `pod` key as a `PodRuntimeConfig` (env, tmp_size, min_cpu, min_memory, min_timeout_seconds). `POD_RUNTIME_CONFIGS` exposes them and the pod builder raises limits to those minimums. Only Go sets one today
- Scripts mount at `/scripts/main.<ext>`. Every language needs an `EXAMPLE_SCRIPTS` entry, and the Python example must parse on every offered version
- The API lists each language's versions newest first, so the frontend takes `versions[0]` as the newest

## Backend: Settings (TOML, secrets from env)

```python
# WRONG: never read config directly from env vars in application code
DATABASE_URL = os.getenv("DATABASE_URL")

# CORRECT: inject via DI (Settings reads the secret env vars itself)
settings: FromDishka[Settings]
```

Config load order (each overrides the previous):
1. `config.toml`: base settings (committed)
2. `config.<worker>.toml`: per-worker overrides (optional)
3. Secrets: `SECRET_KEY`, `MONGO_USER`, `MONGO_PASSWORD`, `REDIS_PASSWORD`. Each one is read from the env var first, then the TOML value, then a dev default, so a missing secret never raises. Production must set all four: the deploy workflow stops when one of their GitHub secrets is empty, since compose would otherwise fall back to the public defaults. `MONGODB_URL` is built from the Mongo values

```python
Settings()                                               # config.toml + secrets
Settings(config_path="config.test.toml")                 # tests + secrets
Settings(override_path="config.saga-orchestrator.toml")  # worker + secrets
```

`Settings` uses `model_config = ConfigDict(extra="forbid")`, so unknown keys are errors.

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
- Discriminated union: `DomainEvent = Annotated[..., Discriminator("event_type")]`
- `event_id` always has a UUID from `default_factory`; never add None checks
- No `correlation_id`; use OpenTelemetry `trace_id`/`span_id` exclusively
- Treat events as immutable: build a new event instead of mutating one. `BaseEvent` is not frozen, so nothing enforces this

### Kafka Topics
One topic per event type, and the topic name is the event type value itself, with no prefix (`execution_requested`, `create_pod_command`). `EventType` is a `str`, so no `.value` is needed.

```python
# Producer (app/events/core/producer.py): stores the event in MongoDB, then publishes
await self.producer.produce(event_to_produce=event, key=execution_id)
# KafkaEventTransport publishes with topic=event_to_produce.event_type
```

### Consumers
Subscribers live in `app/events/handlers.py`, one `<worker>_router()` factory per consumer that returns a `KafkaRouter`. The router carries the ack policy and middlewares; the handler takes the body and the service and does nothing else.

```python
def saga_router() -> KafkaRouter:
    router = KafkaRouter(
        ack_policy=AckPolicy.ACK,
        middlewares=(DeadLetterMiddleware, idempotent(KeyStrategy.EVENT_BASED, ttl_seconds=3600)),
    )

    @router.subscriber(EventType.EXECUTION_REQUESTED, group_id="saga-orchestrator")
    async def on_execution_requested(body: ExecutionRequestedEvent, saga: FromDishka[SagaOrchestrator]) -> None:
        await saga.handle_execution_requested(body)

    return router
```

- Pass the `EventType` member as the topic, never a string literal
- String literal `group_id` per consumer group
- One topic per subscriber, no filtering inside handlers. The one exception is the API's `sse-bridge-pool` subscriber, which takes the 17 execution, result and pod event types in one handler and forwards them to Redis for SSE
- Consumers that must not run a handler twice put `idempotent(strategy, ttl_seconds=...)` from `app/events/middlewares.py` on their router
- Consumers whose failures should be retried put `DeadLetterMiddleware` first on their router. It saves the failed event to the DLQ with the consumer group, and the dlq-processor republishes it with headers that `RetryTargetMiddleware` (on every broker) uses to skip it in the other groups. The SSE bridge has none, since a late SSE push is worse than a missed one
- Don't wrap handlers to count failures: FastStream's `KafkaTelemetryMiddleware` already records them under `error_type` on `messaging_process_duration_seconds`

### Worker Pattern
Each `backend/workers/run_<worker>.py` follows the same order:

1. `Settings(override_path="config.<worker>.toml")`
2. `init_beanie()` on a tz-aware `AsyncMongoClient`, before the container exists
3. `create_<worker>_container(settings)`
4. Get `KafkaBroker` from the container and `broker.include_router(<worker>_router())` if the worker consumes
5. `setup_dishka(container, broker=broker, auto_inject=True)`
6. `FastStream(broker, on_startup=[...], on_shutdown=[...]).run()`; APScheduler jobs start in `on_startup`

| Worker | Purpose |
|--------|---------|
| k8s_worker | Consumes create/delete pod commands, creates executor pods and ConfigMaps, applies the executor NetworkPolicy |
| pod_monitor | Watches executor pods (watch cycle every 5s) and publishes pod and execution events; no subscribers |
| result_processor | Consumes completed, failed and timeout events, stores results, publishes result_stored or result_failed; moves the stored status to scheduled or running on pod_scheduled and pod_running |
| saga_orchestrator | Runs execution sagas, schedules the queue every 10s, checks saga timeouts every 30s |
| dlq_processor | APScheduler only (no Kafka consumer), retries due DLQ rows every 10s for the consumer group that failed |
| event_replay | APScheduler only, cleans up replay sessions older than 48h every 6h; replays themselves run in the API |

The API process consumes too: `sse-bridge-pool` and `notification-service` are registered in `app/core/dishka_lifespan.py`.

## Frontend: Svelte 5 Runes (CRITICAL)

**Never use Svelte 4 patterns:** no `export let`, no `$:` reactive statements, no `writable()`/`readable()` stores in `.svelte` files.

```svelte
<script lang="ts">
    // Props: replaces `export let`
    interface Props {
        user: UserResponse;
        config: Config | null;
        onSave: () => void;
        children?: Snippet;           // for slot-like composition
    }
    let { user, config = $bindable(null), onSave, children }: Props = $props();

    // Local reactive state: replaces `let` reactivity
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

    async login(username: string, password: string): Promise<boolean> { ... }
    async logout(): Promise<void> { ... }
}
export const authStore = new AuthStore();
```

## Frontend: TypeScript

Strict mode plus extra strictness in `tsconfig.json`:
- `"strict": true`
- `"noUncheckedIndexedAccess": true`: array/object access returns `T | undefined`
- `"noImplicitReturns": true`
- `"verbatimModuleSyntax": true`: use `import type` for type-only imports

Imports go through the package.json subpath imports (SvelteKit 3 dropped `$lib`), always with the file extension; never relative `../../lib/`:
```text
#lib/*        = src/lib/*         e.g. #lib/api/index.ts, #lib/formatters.ts
#components/* = src/components/*  e.g. #components/Header.svelte
#stores/*     = src/stores/*      e.g. #stores/auth.svelte.ts
#routes/*     = src/routes/*      e.g. #routes/admin/users/+page.svelte (tests)
#test/*       = src/__tests__/*   e.g. #test/test-utils.ts
```

`tsconfig.json` extends `$app/tsconfig`, which `svelte-kit sync` generates; `npm run check` and `npm run lint` run it first.

Use `interface` for object shapes, `type` for unions/intersections/aliases. Define prop interfaces explicitly before `$props()`.

## Frontend: API Client

Hard rule: `docs/reference/openapi.json` and everything under `frontend/src/lib/api/` come from the generators only. Never edit them by hand, not even a one-line fix; change the backend (routes, schemas) and regenerate. The Generated API workflow regenerates both from the code on every PR and fails on any difference, so a hand edit can't merge.

`npm run generate:api` reads `../docs/reference/openapi.json`, and `./deploy.sh types` regenerates the spec only when that file is missing. After any backend API change, regenerate the spec first:
```bash
# From project root
./deploy.sh openapi   # writes docs/reference/openapi.json from create_app()
./deploy.sh types     # runs npm run generate:api into frontend/src/lib/api/
```

Function names are derived from URL paths: `getUserRateLimitsApiV1AdminRateLimitsUserIdGet`.

Anything that comes from the backend comes from `#lib/api/index.ts`, never from a hand-written copy: types, enum values, validation rules, defaults, URLs and SSE streams. The generator emits runtime enums and a Zod schema per model, and the index re-exports the client and the schemas, so the copies have nothing to add and only drift.

Timestamps stay the ISO strings the API sends, typed `string` by the generated types, in responses, request bodies and SSE events alike. Nothing converts them: the formatters in `#lib/formatters.ts` take the string and parse it only to display it, and test fixtures give timestamps as ISO strings.

```typescript
import { UserRole, zUserCreate, client, type ExportEventsApiV1AdminEventsExportExportFormatGetData } from '#lib/api/index.ts';

Object.values(UserRole);                        // option lists, never a literal array
zUserCreate.safeParse(form);                    // the spec's rules (email format, minLength)
zEditorSettingsInput.parse({});                 // the API's defaults
client.buildUrl<ExportEventsApiV1AdminEventsExportExportFormatGetData>({ url: '/api/v1/admin/events/export/{export_format}', ... });
```

UI-only maps keyed by a generated enum (`Record<ExecutionStatus, string>` for badge colors) are fine, since the compiler flags a missing value. A map of display text is not: every API name has one spelling in the UI.

- A label, column header, detail row or filter for an API field shows `fieldTitle(key)` from `#lib/formatters.ts`, which titles the key the way Pydantic does in the spec (`created_at` is "Created At"). A hint goes in a description next to the field, never into its label
- `DataTable` titles each column by its id, so a column is named after its API key and has no `header`
- Enum values show exactly as the API sends them, and a boolean reads Yes or No through `formatBoolean`
- ESLint rejects literal text inside `<label>`, formsnap's `Label`, `<dt>` and `<th>`, and a `header` on a column. A UI-only label (one that names no API field) goes outside those elements or on the control's `aria-label`

Server state goes through TanStack Query with the options the `@tanstack/svelte-query` plugin generates, never a hand-rolled loading flag, polling loop, cache or retry. A component calls the query or mutation for the data it renders; a page doesn't fetch on behalf of its children, since the query cache already shares one request between them. Every page does this; only the three SSE streams call the SDK directly. `docs/frontend/server-state.md` has the details.

```typescript
import { createMutation, createQuery, keepPreviousData, useQueryClient } from '@tanstack/svelte-query';
import { listSagasApiV1SagasGetOptions, cancelSagaApiV1SagasSagaIdCancelPostMutation, listSagasApiV1SagasGetQueryKey } from '#lib/api/index.ts';

// reads: the callback is reactive, so new filters or a new page are a new key and a new fetch
const list = createQuery(() => ({
    ...listSagasApiV1SagasGetOptions({ query: { state, skip, limit } }),
    placeholderData: keepPreviousData,
    refetchInterval: 5_000,               // polling; pauses in a hidden tab, stops on unmount
}));

// writes: invalidate what the write changed
const queryClient = useQueryClient();
const cancel = createMutation(() => ({
    ...cancelSagaApiV1SagasSagaIdCancelPostMutation(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: listSagasApiV1SagasGetQueryKey() }),
}));
```

`src/lib/query-client.ts` holds the one client, provided by the root layout. It retries a query twice on a network error or a 5xx, never a mutation, and shows failures through its cache handlers. Use `isPending` for first-load spinners and `isFetching` for refresh buttons. Outside components (the auth store), use `queryClient.query(options)`; inside, a form starts over from its query data whenever that changes (see the settings pages) and saves through a mutation that calls `setQueryData`.

## Frontend: Error Handling & API Interceptors

The fetch error interceptor in `src/lib/api-interceptors.ts` wraps every failure in an `ApiError` (`src/lib/api-error.ts`) that keeps the HTTP status, since `throwOnError` would throw only the body. The query client's cache `onError` then calls `showApiError`, once a query has used up its retries:

| Status | Action |
|--------|--------|
| 401 | Clears auth. If the user was signed in: warning toast "Session expired. Please log in again.", saves the path to `redirectAfterLogin`, goes to `/login` |
| 403 | Toast error "Access denied." |
| 422 | Toast error "Validation error: ..." with the formatted field errors |
| 423 | Toast warning (account locked) |
| 429 | Toast warning "Too many requests. Please slow down." |
| 500+ | Toast error "Server error. Please try again later." |
| Other 4xx | Toast error with the response `detail` |
| Network | Toast error "Network error. Check your connection." |

A 401 also empties the query cache, as `authStore.clearAuth()` does. Mutations with `meta: { inlineErrors: true }` (the login and register forms) skip only the 401, network and other-4xx handling and show `getErrorMessage(mutation.error, ...)` under the form; 403, 422, 423, 429 and 5xx still toast. The CSRF token (`X-CSRF-Token`) is attached to every non-GET request from `authStore.csrfToken`.

**Do not add try/catch around API calls**; the cache handlers do the display. To react to one specific failure, pass `onError` to `mutate` (the editor turns a 404 on update into a create). Two kinds of catch are fine: the auth store's `verifyAuth`, which tells a 401 from a network error, and `.catch(() => null)` on an awaited `queryClient.query()` or `mutateAsync()` that only needs to know whether it worked (the admin detail modals, the editor's execution start), since the cache handler has already shown the error.

## Frontend: Auth Store

- Auth state lives in `#stores/auth.svelte.ts`: `isAuthenticated`, `user` (the generated `UserResponse`, never a copy of its fields) and `csrfToken`. It persists to `sessionStorage` under one key, `authState`, as a JSON blob with a `timestamp`, checked against `zUserResponse` when it's read back
- The login page's mutation passes the response to `authStore.startSession(login)`, which stores the session and loads the full profile; the header's logout mutation calls `authStore.clearAuth()`, which also empties the query cache
- `verifyAuth()` reads the profile through `queryClient.query()` with a 30-second stale time, so checks share one answer and one request; on a network or server error it returns the last answer (offline-first)
- `authStore.waitForInit()` awaits one-time initialization before checking auth

## Frontend: Routing

SvelteKit's filesystem router: a page is `src/routes/<path>/+page.svelte`, and the root `+layout.ts` sets `ssr = false`, so it's a client-rendered SPA served through adapter-static's `200.html` fallback. Guards are `load` functions, which run before the page mounts:

```typescript
// src/routes/(auth)/+layout.ts guards /editor, /settings, /notifications; admin/+layout.ts uses requireAdmin
import { requireAuth } from '#lib/auth-guard.ts';
import type { LayoutLoad } from './$types';

export const load: LayoutLoad = async ({ url }) => {
    await requireAuth(url);
};
```

Navigation: plain `<a href>` for links (SvelteKit handles them), `goto('/path')` from `$app/navigation` in code, and `page` from `$app/state` for the current URL. Page titles go in `<svelte:head>` as `<title>Page - Integr8sCode</title>`. Errors while loading or rendering show `src/routes/+error.svelte`.

## Frontend: Overlays

Dialogs, menus, popovers and selects come from bits-ui, imported from npm and styled with our own Tailwind classes; don't copy component source into the repo and don't hand-roll click-outside or arrow-key handling. Dialogs go through `#components/Modal.svelte`, which wraps `Dialog` and keeps the `open`, `title`, `onClose`, `size`, `children` and `footer` props. Menu, popover and select content renders in a `Portal` with `class="floating-panel"`, and each item gets `class="floating-item"` (both in `styles/components.css`). A menu item that navigates renders an `<a href>` through its `child` snippet.

Tooltips use bits-ui `Tooltip` with `class="tooltip-content"`; the root layout holds the one `Tooltip.Provider`, and `renderWithQueryClient` adds it in tests. Shared styling is Tailwind classes in `styles/components.css` (`.btn-*`, `.badge-*`, `.card`, `.alert-*`, `.form-*-standard`); plain inputs, selects and checkboxes get their look from the base layer in `app.css`, and page-only rules go in `styles/pages.css`. Add a class there only when several components share it.

## Frontend: Forms

Forms go through `apiForm(schema, options, initial?)` from `#lib/forms.ts`: superforms in SPA mode on a generated Zod schema (or one picked, extended or checked from them), with JSON data and our wording from `issueMessage` in `#lib/validation.ts`. `onUpdate` saves through the mutation once `form.valid` is true. Fields use formsnap's `Field`, `Control`, `Label` and `FieldErrors`, with `props` and `$constraints[name]` spread on the input, so the label, `aria-invalid` and `aria-describedby` come wired; the form is `method="post" use:enhance novalidate`, so errors show under the fields instead of as browser bubbles. `filled()` marks a text field that mustn't be sent empty and `optionalText()` one that may stay empty. API errors, such as a taken username, show above the form from the mutation, not as field errors. A dialog the page mounts per open keeps what it needs from its props with `untrack` and reads it before calling `onClose`, since closing clears the page state those props come from. A form over loaded data, like the two settings pages and the rate limits modal, calls `reset({ newState })` in an `$effect` whenever the query data changes, and `isTainted(path)` says what the user changed since.

## Frontend: Tables

Tables run on TanStack Table through `#lib/data-table.ts`. A table component defines its columns with `columnHelper<Row>()`, rendering custom cells with `renderSnippet` and putting cell classes in `meta.class`, then renders `#components/DataTable.svelte` (a `<table>` from `lg` up, a card per row below it, both from the same columns) and `#components/Pagination.svelte`. Don't write separate mobile markup, and use real buttons or links in cells instead of clickable rows. A server-paged table uses `createServerTable(columns, source)`, where `source.pagination` is a `PaginationState` the page owns and its query reads for `skip`/`limit`; the page index is derived from the filters, so a new filter goes back to page 0. `rowCount` comes from the API's `total`.

## Testing

### Backend (pytest)

```text
backend/tests/
├── unit/      # No infra, fast; the db, redis_client, client and app fixtures raise here
├── e2e/       # Full stack plus K8s (k3s in CI); run inside the backend container
├── contract/  # Grafana dashboard metric contract (grafana_contract marker), no infra
└── load/      # Load test CLI, not collected by pytest
```

Markers registered in pyproject.toml: `unit`, `e2e`, `slow`, `kafka`, `mongodb`, `redis`, `k8s`, `performance`, `admin`, `grafana_contract`. pytest-xdist adds `xdist_group`.

`asyncio_mode = "auto"`, so a test is `async def` when it awaits and a plain `def` otherwise; about a quarter of the suite is sync. Key fixtures: `test_settings`, `app`, `client`, `scope`, `redis_client`, `test_user`, `test_admin`, `another_user` (the last three are logged-in `httpx2.AsyncClient`s with the CSRF header set).

Test quality rules:
- Test API responses precisely: status code **and** response body contents
- Use `@pytest.mark.parametrize` over duplicate test bodies
- Mock at service boundaries using `unittest.mock.AsyncMock`
- Prefer DI over `monkeypatch`/patching

```python
@pytest.mark.parametrize("path", ["/api/v1/admin/users/", "/api/v1/admin/settings/"])
async def test_admin_routes_reject_regular_users(test_user: AsyncClient, path: str) -> None:
    response = await test_user.get(path)
    assert response.status_code == 403
    assert response.json()["type"] == "AdminAccessRequiredError"
```

SSE routes need a streaming transport, because `httpx2.ASGITransport` waits for the whole body. Use `streaming_client(app, user)` from `tests/e2e/conftest.py` (built on its `StreamingASGITransport`) and read events with httpx2's `client.sse()`:

```python
async with (
    streaming_client(app, test_user) as client,
    client.sse("/api/v1/events/notifications/stream") as source,
):
    assert source.response.status_code == 200
```

Isolation: only Redis is split per worker; `test_settings` sets `REDIS_DB` to the xdist worker number mod 16. MongoDB is one shared database, so tests isolate by unique ids (uuid usernames, fresh executions). Tests that touch shared global state (system settings, Kafka consumer groups, the DLQ, execution concurrency) carry `@pytest.mark.xdist_group("name")`; `addopts` runs `-n auto --dist=loadgroup`, so each group stays on one worker.

### Frontend (Vitest)

```typescript
// Always hoist mocks
const mocks = vi.hoisted(() => ({
    someApiFunction: vi.fn(),
}));

vi.mock('#lib/api/index.ts', async (importOriginal) => ({
    ...(await importOriginal<typeof import('#lib/api/index.ts')>()),
    someApiFunction: (...args: unknown[]) => mocks.someApiFunction(...args),
}));
```

- Tests sit next to the source in `__tests__/` directories
- `vitest.setup.ts` already mocks `#lib/api/sdk.gen.ts` (SDK functions only; enums, Zod schemas, the client and the TanStack options stay real, and the options call the mocks), `initializeApiInterceptors` (so no toast handler is set), `svelte-sonner` and `$app/navigation`, stubs storage, and runs `cleanup()`, clears the query cache and seeds faker before every test; override a mock per file with `vi.mock`, spread `importOriginal()` into a `#lib/api/index.ts` or `#lib/formatters.ts` factory so the real exports stay available, and mock `$app/state` in the file when a component reads `page`
- bits-ui content renders in a portal, so query it through `screen` or `document.body`, not the render container. happy-dom gives every element a 0x0 box, so outside clicks can't be tested there; cover them in Playwright
- Fixtures come from the generated Faker factories in `#lib/api/@faker-js/faker.gen.ts` (`fakeUserResponse()` and one per schema), with the values a test depends on spread over them, never a local copy of an API type or an `as any`. The setup seeds faker before every test, so fakes repeat from run to run but shift when the spec changes: set every field the test asserts on. API calls are mocked at the SDK functions, so the MSW plugin isn't used; `mockApi(fn).ok(data)` takes the data type from `fn`'s generated return type, and `mockStreamEvents(fn, ...events)` feeds an SSE function
- Components that run queries render with `renderWithQueryClient(Component, props)`; state that builds queries outside a component (the editor's execution state) is created with `createInQueryContext(factory)`. Both come from `#test/test-utils.ts`. `mockApi(fn).err()` rejects when the call passes `throwOnError`, as the generated options do, so check SDK calls with `expect.objectContaining`; reject with an `ApiError` when the code branches on the status
- `vi.clearAllMocks()` in `beforeEach`
- `await tick()` after render, `waitFor()` for async state
- Coverage thresholds: statements 92, branches 76, functions 90, lines 92; the generated client (`src/lib/api/`) is excluded

### E2E (Playwright)
- Chromium only, base URL `https://localhost:5001`, `ignoreHTTPSErrors: true` (self-signed certs), `timeout: 10000`, `expect.timeout: 3000`
- Run through npm scripts: `npm run test:e2e:deps` and `npm run test:e2e:browsers` once, then `npm run test:e2e`. Outside CI the config starts `npm run dev` unless a server is already up
- Users are seeded by the `user-seed` compose service (`scripts/seed_users.py`) on every `./deploy.sh dev`; rerun it with `docker compose run --rm user-seed`
- Log in by username: `user` / `user123` and `admin` / `admin123` (`frontend/e2e/fixtures.ts`). The seeded emails are user@integr8scode.com and admin@integr8scode.com

## CI Gates (All Must Pass)

```bash
# Backend (from backend/)
uv run ruff check . --config pyproject.toml           # rules E, F, B, I, W; W293 ignored; tests included
uv run mypy --config-file pyproject.toml --strict .
uv run python -m scripts.check_orphan_modules         # grimp orphan module detection
uv run pytest tests/unit
uv run pytest tests/contract -m grafana_contract

# Frontend (from frontend/)
npm run lint
npm run stylelint
npm run format:check
npm run check           # svelte-check, 0 errors and 0 warnings
npm run build
npm run test:coverage   # Vitest with coverage thresholds

# Generated API (from the project root): must leave no diff
./deploy.sh openapi && (cd frontend && npm run generate:api)
git status --porcelain -- docs/reference/openapi.json frontend/src/lib/api
```

CI also runs the backend E2E suite and Playwright against a k3s stack, plus bandit and image scans. The grimp check (`backend/scripts/check_orphan_modules.py`) fails on any module in `app` that no other module imports. It skips `app.main`, the only whitelisted entry point, and `__init__.py` files that hold nothing but a docstring.

## Security Constraints

- K8s executor pods: non-root (uid 1000), read-only root filesystem, all capabilities dropped, no privilege escalation, `seccomp: RuntimeDefault`, `automountServiceAccountToken: false`
- NetworkPolicy: the k8s worker applies `executor-deny-all`, which denies all ingress and egress for executor pods
- Passwords: bcrypt via pwdlib (`PasswordHash((BcryptHasher(rounds=settings.BCRYPT_ROUNDS),))`)
- Login lockout after `max_login_attempts` failures (default 5, for 15 minutes), configurable in admin system settings
- Request size limit enforced by ASGI middleware (streams the body and rejects before the full payload is in memory; default 10MB)
- Rate limiting: Redis-backed, keyed by the user id of a valid access token (the middleware verifies it, since it runs before auth) or else by client IP, and it fails open when Redis errors. Default rules per 60s: execution 10, auth 20, admin 100, sse 5, websocket 5, api 60. Login, register, logout and `/api/v1/health/` skip the middleware
- CSRF: double-submit cookie pattern. `access_token` (httpOnly) plus `csrf_token` (readable) cookies, and the `X-CSRF-Token` header is required for POST, PUT, PATCH and DELETE. Login, register and unauthenticated requests are exempt
- Sensitive data (API keys, tokens, passwords, connection-string credentials) is redacted before logging
- Never log user-controlled data via string interpolation; always use structured keyword args
