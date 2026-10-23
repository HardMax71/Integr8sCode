# Integr8sCode: Agent Instructions

Platform for running scripts online in isolated Kubernetes pods. Users write Python, Node.js, Ruby, Bash or Go in a Svelte 5 frontend, the FastAPI backend publishes the request to Kafka, and the worker runs it in its own pod.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Svelte 5 (runes), SvelteKit 3 (adapter-static SPA) on Vite 8, TanStack Query 6, TanStack Table 9, bits-ui 2, superforms 3 with formsnap, mode-watcher, TypeScript 6 strict, TailwindCSS 4, Node 26 |
| Backend | FastAPI, Dishka DI, Beanie ODM (MongoDB), Python 3.14 (backend/.python-version), async throughout, httpx2 for HTTP |
| Events | Kafka (KRaft, no ZooKeeper) + FastStream (Pydantic JSON) |
| Worker | one process (`app/worker.py`): execution scheduler, k8s worker, pod monitor, result processor, DLQ retries |
| Infra | MongoDB 9, Redis 8; optional Grafana, Jaeger, Victoria Metrics, Loki, OpenSearch, OTel Collector plus its host-metrics collector (`--observability`) and Kafdrop (`--debug`) |
| Runtimes | Python 3.11 to 3.14, Node 22/24/26, Ruby 3.3/3.4/4.0, Bash 5.3, Go 1.26/1.27 (app/runtime_registry.py) |

## Key Directory Map

```text
backend/
├── app/
│   ├── api/routes/          # FastAPI route handlers (DishkaRoute), admin/ for admin routers
│   ├── core/                # providers.py (all Dishka providers), container.py, middlewares/, metrics/,
│   │                        # tracing/, exceptions/, security.py, logging.py, utils.py (StringEnum)
│   ├── db/                  # Beanie documents, the stored entities (db/docs/), and repositories (db/repositories/)
│   ├── dlq/                 # DLQ manager and models
│   ├── domain/              # Value objects, results and update changes (dataclasses, TypedDicts), events, enums, exceptions
│   ├── events/              # handlers.py (Kafka routers), middlewares.py (idempotency), core/ (producer, transport)
│   ├── infrastructure/      # kafka/topics.py: event type groupings
│   ├── schemas_pydantic/    # API request and response schemas
│   ├── services/            # Business services, constructor-injected via Dishka
│   ├── scripts/             # entrypoint.sh mounted into executor pods
│   ├── main.py              # create_app()
│   ├── worker.py            # the worker process: Kafka consumers, pod watch, scheduled jobs
│   ├── runtime_registry.py  # Languages, versions, images, per-language pod settings
│   └── settings.py          # Settings: TOML plus secrets from env
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
    ├── lib/admin/           # Admin utilities: events/, rate-limits/
    ├── lib/editor/          # Execution state, the open script (draft), CodeMirror languages
    ├── lib/notifications/   # Notification SSE stream
    ├── lib/query-client.ts  # the one TanStack Query client, provided by the root layout
    └── styles/              # Global CSS

grafana/                     # grafana.ini and provisioning/: datasources, dashboards, alert rules
host-metrics/                # otel-host-metrics.yaml, the host's CPU, memory, disk and network
loki/                        # loki-config.yaml
opensearch/                  # start.sh (the entrypoint), the logs index template and retention policy
otel-collector/              # otel-collector-config.yaml: every pipeline, span metrics (signaltometrics), exporters
victoria-metrics/            # scrape.yaml
```

backend/ and frontend/ are the build contexts of the two images. Each other folder holds the config of the compose service it's named after, mounted read-only.

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
./deploy.sh dev --observability  # plus Grafana, Jaeger, Victoria Metrics, Loki, OpenSearch, OTel Collector, host-metrics
./deploy.sh dev --debug          # observability plus Kafdrop
./deploy.sh down                 # stop
./deploy.sh openapi              # regenerate docs/reference/openapi.json
./deploy.sh types                # regenerate frontend/src/lib/api/ from that spec
```

`npm run dev` serves HTTPS when ./certs/server.key and server.crt exist and proxies /api to `https://backend:443` with the certificate checked, so it needs `NODE_EXTRA_CA_CERTS` pointing at the backend's `server.crt` (the `backend_tls_cert` volume). `backend` only resolves inside the compose network, so on the host the API calls fail. The compose `frontend` service already serves a production build on :5001; rebuild it with `./deploy.sh dev --build` after frontend changes.

Plain `uv run pytest` also collects tests/e2e, which needs the full stack, so always pass a path. E2E tests run inside the backend container against a running stack, the way CI does it (CI copies config.test.toml over config.toml before starting the stack):

```bash
docker compose exec -T backend sh -c 'uv sync --group test --no-dev --frozen --no-install-project && pytest tests/e2e'
```

## Critical Architecture Rules

These layer boundaries hold throughout the codebase:

| Layer | Technology | Rule |
|-------|-----------|------|
| Entities | Beanie `Document` in `db/docs/` | The one model per stored entity. Services and repositories take and return documents |
| Domain types | stdlib `@dataclass` and `TypedDict` in `domain/` | Value objects, results, filters and update changes. None repeats a document's fields |
| Schema models | Pydantic `BaseModel` in `schemas_pydantic/` | Presentation only (request/response). Nothing under `services/` or `db/` imports them |

- Routes call services with keyword arguments taken from the request schema, and services build documents with the document's constructor
- Routes return `SchemaResponse.model_validate(document)`; `from_attributes=True` goes on the schema's `model_config`, never as a kwarg to `model_validate()`
- An update's changes are a `TypedDict` with `total=False` in `domain/` (`SavedScriptChanges`). The route builds it with a module-level `TypeAdapter(SavedScriptChanges).validate_python(body.model_dump(exclude_unset=True))`, so a key left out keeps its value and `None` clears it, and the repository applies it with `doc.set({**changes, "updated_at": now})`
- A domain value embedded in a document (`ResourceUsageDomain`, `ReplayConfig`) is a dataclass that the document registers in `Settings.bson_encoders` with `dataclasses.asdict`; Pydantic converts it back on read
- A result that holds documents (`UserListResult`) sits next to the repository or service that returns it, since `domain/` never imports `db/docs/`
- No `**model_dump()`, `**asdict()` or `__dataclass_fields__` field sets to copy between models

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
from typing import Any, Annotated, Literal, NoReturn, NamedTuple, TypedDict, NotRequired, Protocol
from collections.abc import Callable, Mapping, Sequence, Iterable, Iterator, Awaitable, AsyncIterator, AsyncGenerator
```

No `if TYPE_CHECKING:` imports and no `from __future__ import annotations`: Python 3.14 evaluates annotations lazily. An import that would need the guard means the type sits in the wrong layer, so move it to the layer that already imports both sides.

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
- No function or class defined inside a function, in app code or tests. A callback is a module-level function or a bound method; one that must carry per-call state (an ASGI `send` wrapper holding one request's headers) is a small module-level class. A tenacity callback reads the retried call's arguments from `RetryCallState.args` instead of closing over them

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
| Domain value objects, results and filters | API request/response schemas |
| Values embedded in documents | Kafka event payloads (FastStream) |
| Simple data containers without validation | Beanie documents, the stored entities |

An update's changes are a `TypedDict` with `total=False`, not a dataclass with None defaults.

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

Every error the API returns is one body, `ErrorResponse`: `{"status": 404, "detail": "..."}`, the `status` and `detail` members of RFC 9457 problem details. The handlers in `app/core/exceptions/handlers.py` give it to a `DomainError` (with the status its class maps to), to FastAPI's `HTTPException` and request validation errors (one line of `field: message` pairs joined by `; `) and to anything unexpected (500 "Internal server error"). The rate-limit, CSRF and request-size middlewares reject with the same body. `create_app` declares it as every route's `default` response, so the spec and the generated client know exactly one error type.

Rules:
- Repositories return `T | None` for reads and **never raise `NotFoundError`**; they raise only for write-constraint violations (e.g. `ConflictError` for a duplicate key)
- Services check `None` from the repo, log, and raise a domain-specific `NotFoundError` subclass; services never return `None` to route handlers
- Route handlers call the service and return the schema. They **never** raise `HTTPException` for domain-not-found cases; the global handler turns the exception into a 404
- Use `raise SpecificError(...) from original_exc` to preserve exception chains
- Never catch `Exception` broadly; catch specific exception types (the two allowed cases follow)

A catch-all is allowed in two cases only. The first records or logs, then re-raises: `IdempotencyMiddleware` and `DeadLetterMiddleware` in `app/events/middlewares.py` release the idempotency key and save the event to the DLQ, `ExecutionService` marks the execution as errored before raising `InfrastructureError`, and `KubernetesWorker.create_pod` marks its `pod.create` span failed. The second is a loop or batch boundary that must survive one bad item: the execution scheduler's queue loop (`schedule_pending`, a pod that can't be created fails its execution and the loop goes on), the pod monitor's watch cycle (`PodMonitor.watch_cycle`) and per-event processing, notification delivery and the scheduled-notification batch, DLQ batch retry and per-event replay. A new catch-all needs the same justification and must log or record the error; never swallow it silently.

```python
# Repository: returns None for reads; raises only on write constraints
async def get_user(self, username: str) -> UserDocument | None:
    return await UserDocument.find_one(UserDocument.username == username)

async def create_user(self, user: UserDocument) -> None:
    try:
        await user.insert()
    except DuplicateKeyError as e:
        raise ConflictError("User already exists") from e

# Service: checks None and raises a domain exception (global handler returns 404)
async def get_user(self, user_id: str) -> UserDocument:
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

The API error response schema is `ErrorResponse(status: int, detail: str)` from `app/schemas_pydantic/common.py`.

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
- Container factories live in `app/core/container.py`, one per process: `create_app_container` and `create_worker_container`
- `FromDishka[ServiceType]` injects into route handlers (`dishka.integrations.fastapi`) and Kafka subscribers (`dishka_faststream`)
- `@inject` decorator when needed outside routes (e.g. the `admin_user` dependency)
- `setup_dishka(container, broker=broker, auto_inject=True)` from `dishka_faststream` runs **after** subscriber registration and **before** the broker starts, in the worker and in the API lifespan
- Never instantiate services directly; always use DI

## Backend: Domain Types (Dataclasses and TypedDicts)

```python
from dataclasses import dataclass
from typing import TypedDict

@dataclass
class ResourceUsageDomain:
    """Resource usage metrics from script execution."""

    execution_time_wall_seconds: float = 0.0
    cpu_time_jiffies: int = 0
    clk_tck_hertz: int = 0
    peak_memory_kb: int = 0


class SavedScriptChanges(TypedDict, total=False):
    """Fields an update sets; a missing key keeps the stored value and None clears the description."""

    name: str
    script: str
    lang: str
    lang_version: str
    description: str | None
```

- Pure Python, no Pydantic validation at construction
- No dataclass repeats the fields of a document: the document is the entity
- `event_id` and other UUID fields always use `default_factory`; never add None checks
- Nested dataclass fields: `filter: ReplayFilter = field(default_factory=ReplayFilter)`
- `domain/` imports nothing from `db/docs/`, since the documents import domain values

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
- `ErrorResponse(status: int, detail: str)` is the one error shape; list a route's error codes with `{"model": ErrorResponse}`

## Backend: Beanie ODM (MongoDB)

```python
from typing import Annotated

from beanie import Document, Indexed
from pydantic import ConfigDict, Field

class UserDocument(Document):
    username: Annotated[str, Indexed(unique=True)]
    email: Annotated[EmailStr, Indexed(unique=True)]
    user_id: Annotated[str, Indexed(unique=True)] = Field(default_factory=lambda: str(uuid4()))
    role: UserRole = UserRole.USER
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    class Settings:
        name = "users"
        use_state_management = True
```

- Documents in `app/db/docs/`; only top-level collection models extend `Document`. They are the entities services work with
- An embedded value is a domain dataclass listed in `Settings.bson_encoders` with `dataclasses.asdict` (no `EmbeddedDocument`)
- `Document.__init__` needs `init_beanie`; unit tests get it from a session fixture that runs it on a mocked database
- lazy-model ships no `py.typed` yet ([BeanieODM/lazy_model#15](https://github.com/BeanieODM/lazy_model/issues/15)), so mypy sees a document's constructor and its Pydantic methods (`model_validate`, `model_dump`) as `Any`. Assign their results to annotated variables: `doc: EventDocument = EventDocument.model_validate(data)`
- Indexed fields are `Annotated[type, Indexed(...)]`, so mypy sees the real type; an optional one is `Annotated[type | None, Indexed()]`, since `Indexed(type) | None` creates no index
- `arbitrary_types_allowed=True` required on Document models
- Compound indexes via `Settings.indexes = [IndexModel([...])]`
- Update pattern: `await doc.set({**changes, "updated_at": now})`, or `await doc.update({"$set": changes})` when nothing is added
- Atomic updates: `find_one().update(Set({...}), response_type=UpdateResponse.NEW_DOCUMENT)`

## Backend: Repository Pattern

```python
class UserRepository:
    def __init__(self, logger: structlog.stdlib.BoundLogger) -> None:
        self.logger = logger

    async def get_user(self, username: str) -> UserDocument | None:
        return await UserDocument.find_one(UserDocument.username == username)

    async def create_user(self, user: UserDocument) -> None:
        try:
            await user.insert()
        except DuplicateKeyError as e:
            raise ConflictError("User already exists") from e

    async def update_user(self, user_id: str, changes: UserChanges) -> UserDocument | None:
        doc = await UserDocument.find_one(UserDocument.user_id == user_id)
        if not doc:
            return None
        await doc.set({**changes, "updated_at": datetime.now(timezone.utc)})
        return doc
```

- Location: `app/db/repositories/`
- Take and return documents and domain types, never schema models
- A create takes the document the service built and inserts it
- An update takes a changes `TypedDict` and applies it as is
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
        tracer: trace.Tracer,
        idempotency_manager: IdempotencyManager,
        runtime_settings: RuntimeSettingsLoader,
    ) -> None:
        self.execution_repo = execution_repo
        self.producer = producer
        self.settings = settings
        self.logger = logger
        self._tracer = tracer
        self.idempotency_manager = idempotency_manager
        self._runtime_settings = runtime_settings
```

- Location: `app/services/`
- Constructor injection: repo, producer, logger, settings, and `trace.Tracer` when the service makes spans
- New metrics come from spans: put the facts on a span as attributes (`queue.priority`, `queue.outcome`) and define the metric under `signaltometrics` in `otel-collector/otel-collector-config.yaml`. There are no metric classes: `app/core/metrics/` only sets up the OTLP `MeterProvider` for the instrumentations ([#389](https://github.com/HardMax71/Integr8sCode/issues/389)). A gauge needs a job that reports it on a timer
- Publish events via `UnifiedProducer`: `await self.producer.produce(event_to_produce=event, key=execution_id)`. An event sent after its work is done, which no caller waits on (auth and settings events, pod progress, the result processor's announcements), goes through `produce_or_log`: it still raises a MongoDB error but only logs a Kafka one, so a Kafka outage doesn't fail a login or leave a finished pod behind
- Services orchestrate domain logic; no direct DB or HTTP calls
- Services build new documents with the document's constructor and hand them to the repository; they never import `app.schemas_pydantic`
- Always check `None` from repos and raise a domain-specific `NotFoundError` subclass (e.g. `ExecutionNotFoundError`, `SavedScriptNotFoundError`); never return `None` to a route

## Backend: Runtime Registry

`app/runtime_registry.py` is the one place that defines languages and versions.

- `LANGUAGE_SPECS` lists each language's versions newest first, plus image template, file extension and interpreter. A unit test enforces the order
- `DEFAULT_LANG` ("python") and `DEFAULT_LANG_VERSION` (the first python version, currently 3.14) are the only defaults. Every `lang` and `lang_version` default in schemas, domain models, documents and `ExecutionService` reads them, and a test pins that. Never hardcode a version
- `Settings.SUPPORTED_RUNTIMES` and `ExecutionRequest` validation both derive from `LANGUAGE_SPECS`. Removing a version makes new executions, retries and saved-script writes on it fail with 422; stored scripts still load
- Per-language pod settings go in the spec's optional `pod` key as a `PodRuntimeConfig` (env, tmp_size, min_cpu, min_memory, min_timeout_seconds; the minimums default to zero, never None). `POD_RUNTIME_CONFIGS` exposes them and the pod builder raises limits to those minimums. Only Go sets one today
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
2. `config.worker.toml`: the worker's override (optional)
3. Secrets: `SECRET_KEY`, `MONGO_USER`, `MONGO_PASSWORD`, `REDIS_PASSWORD`. Each one is read from the env var first, then the TOML value, then a dev default, so a missing secret never raises in `Settings`. Compose has no defaults for them: `./deploy.sh dev` copies `.env.example` to `.env`, the deploy writes `.env` from the GitHub secrets, and compose refuses to start while one is empty. `MONGODB_URL` is built from the Mongo values

```python
Settings()                                               # config.toml + secrets
Settings(config_path="config.test.toml")                 # tests + secrets
Settings(override_path="config.worker.toml")             # worker + secrets
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
One topic per event type, and the topic name is the event type value itself, with no prefix (`execution_requested`, `pod_created`). `EventType` is a `str`, so no `.value` is needed.

```python
# Producer (app/events/core/producer.py): stores the event in MongoDB, then publishes
await self.producer.produce(event_to_produce=event, key=execution_id)
# KafkaEventTransport publishes with topic=event_to_produce.event_type
```

### Consumers
Subscribers live in `app/events/handlers.py`, one `<worker>_router()` factory per consumer that returns a `KafkaRouter`. The router carries the ack policy and middlewares; the handler is a module-level function that takes the body and the service and does nothing else, and the factory registers it by calling the subscriber decorator directly.

```python
async def schedule_execution(body: ExecutionRequestedEvent, scheduler: FromDishka[ExecutionScheduler]) -> None:
    await scheduler.handle_execution_requested(body)


def scheduler_router() -> KafkaRouter:
    router = KafkaRouter(
        ack_policy=AckPolicy.ACK,
        middlewares=(DeadLetterMiddleware, idempotent(KeyStrategy.EVENT_BASED, ttl_seconds=3600)),
    )
    router.subscriber(EventType.EXECUTION_REQUESTED, group_id="saga-orchestrator")(schedule_execution)
    return router
```

- Pass the `EventType` member as the topic, never a string literal
- String literal `group_id` per consumer group. The worker's group stays `saga-orchestrator`, the name of the saga orchestrator the scheduler replaced, so its committed offsets carry over
- One topic per subscriber, no filtering inside handlers. The one exception is the API's `sse-bridge-pool` subscriber, which takes the 17 execution, result and pod event types in one handler and forwards them to Redis for SSE
- Consumers that must not run a handler twice put `idempotent(strategy, ttl_seconds=...)` from `app/events/middlewares.py` on their router
- Consumers whose failures should be retried put `DeadLetterMiddleware` first on their router. It saves the failed event to the DLQ with the consumer group, and the worker's DLQ job republishes it with headers that `RetryTargetMiddleware` (on every broker) uses to skip it in the other groups. The SSE bridge has none, since a late SSE push is worse than a missed one
- Don't wrap handlers to count failures: FastStream's `KafkaTelemetryMiddleware` already records them under `error_type` on `messaging_process_duration_seconds`

### Worker Process
Everything outside the API runs in one process, `python -m app.worker` (`backend/app/worker.py`), in this order:

1. `Settings(override_path="config.worker.toml")`
2. `init_beanie()` on a tz-aware `AsyncMongoClient`, before the container exists
3. `create_worker_container(settings)`
4. Get `KafkaBroker` from the container and `broker.include_routers(scheduler_router())`
5. `setup_dishka(container, broker=broker, auto_inject=True)`
6. `start_jobs(container)` prepares the cluster and starts the APScheduler jobs, `PodMonitor.run()` starts as a task, then `FastStream(broker, on_shutdown=[watch.cancel, scheduler.shutdown], after_shutdown=[container.close]).run()`

| Part | Purpose |
|------|---------|
| execution_scheduler | Consumes `execution_requested` and `execution_cancelled`, queues executions in Redis, starts them while slots are free, cancels them; checks the queue every 10s |
| k8s_worker | Creates executor pods and ConfigMaps and deletes cancelled pods when the scheduler calls it; applies the executor namespace, NetworkPolicy and ResourceQuota on startup |
| pod_monitor | Watches executor pods (one 30 s watch after another, in its own task), publishes pod events, hands finished executions to the result processor, deletes the pod and tells the scheduler |
| result_processor | Stores the status and result, then publishes the terminal event and result_stored or result_failed; publishes nothing for an execution that already ended |
| event_replay | Runs the replay session the API scheduled, oldest first (job every 2s): sends the matching stored events to Kafka again; fails sessions a restart cut off when the worker starts |
| dlq_processor | APScheduler only (no Kafka consumer), retries due DLQ rows every 10s for the consumer group that failed |

Inside the worker the parts call each other directly; Kafka only brings the requests in and carries what happened out. New background work goes into this process: a router in `app/events/handlers.py` included next to the scheduler's, or one more APScheduler job. Run one worker replica: the pod watch and the jobs would run once per replica. A TTL index on `completed_at` drops finished replay sessions after 48 hours.

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
Shared state comes from whatever already holds it, never from a wrapper or a copy: who is signed in is `page.data.user` (the root layout's load), server data is the TanStack Query cache, and the theme is mode-watcher's `userPrefersMode`, `mode` and `setMode`. What's left is client state, which goes in a `.svelte.ts` module on a library primitive, such as the editor's open script on runed's `PersistedState`:

```typescript
// lib/editor/draft.svelte.ts: kept in localStorage, not synced across tabs, so two tabs can edit two scripts
export const draft = new PersistedState<Draft>('editorDraft', { script_id: null, name: '', script: '', ...langDefaults }, { syncTabs: false });
```

## Frontend: TypeScript

Strict mode plus extra strictness in `tsconfig.json`:
- `"strict": true`
- `"noUncheckedIndexedAccess": true`: array/object access returns `T | undefined`
- `"noImplicitReturns": true`
- `"verbatimModuleSyntax": true`: use `import type` for type-only imports
- `"noUnusedLocals"` and `"noUnusedParameters"`: svelte-check fails on an unused declaration, in `.svelte` files too. They replace typescript-eslint's `no-unused-vars`, which flags the type parameters a merged declaration has to repeat

Imports go through the package.json subpath imports (SvelteKit 3 dropped `$lib`), always with the file extension; never relative `../../lib/`:
```text
#lib/*        = src/lib/*         e.g. #lib/api/index.ts, #lib/formatters.ts
#components/* = src/components/*  e.g. #components/Header.svelte
#routes/*     = src/routes/*      e.g. #routes/admin/users/+page.svelte (tests)
#test/*       = src/__tests__/*   e.g. #test/test-utils.ts
```

`tsconfig.json` extends `$app/tsconfig`, which `svelte-kit sync` generates; `npm run check` and `npm run lint` run it first.

Use `interface` for object shapes, `type` for unions/intersections/aliases. Define prop interfaces explicitly before `$props()`.

## Frontend: API Client

Hard rule: `docs/reference/openapi.json` and everything under `frontend/src/lib/api/` come from the generators only. Never edit them by hand, not even a one-line fix; change the backend (routes, schemas) and regenerate. CI's `Spec and client match the code` job regenerates both on every PR that touches the backend, the spec or the client, and fails on any difference, so a hand edit can't merge.

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
- ESLint runs eslint-plugin-svelte's recommended rules: keyed `{#each}` blocks, `resolve()` on every link and `goto()`, no `{@html}` (ANSI output renders as spans from anser's tokens). Fix a finding in the code; the repo has no `eslint-disable` comments
- ESLint rejects literal text inside `<label>`, formsnap's `Label`, `<dt>` and `<th>`, and a `header` on a column. A UI-only label (one that names no API field) goes outside those elements or on the control's `aria-label`

Server state goes through TanStack Query with the options the `@tanstack/svelte-query` plugin generates, never a hand-rolled loading flag, polling loop, cache or retry. A component calls the query or mutation for the data it renders; a page doesn't fetch on behalf of its children, since the query cache already shares one request between them. Every page does this; only the three SSE streams and the root layout's session check call the SDK directly. `docs/frontend/server-state.md` has the details.

```typescript
import { createMutation, createQuery, keepPreviousData, useQueryClient } from '@tanstack/svelte-query';
import { listExecutionsApiV1AdminExecutionsGetOptions, updatePriorityApiV1AdminExecutionsExecutionIdPriorityPutMutation, listExecutionsApiV1AdminExecutionsGetQueryKey } from '#lib/api/index.ts';

// reads: the callback is reactive, so new filters or a new page are a new key and a new fetch
const list = createQuery(() => ({
    ...listExecutionsApiV1AdminExecutionsGetOptions({ query: { status, skip, limit } }),
    placeholderData: keepPreviousData,
    refetchInterval: 5_000,               // polling; pauses in a hidden tab, stops on unmount
}));

// writes: invalidate what the write changed
const queryClient = useQueryClient();
const updatePriority = createMutation(() => ({
    ...updatePriorityApiV1AdminExecutionsExecutionIdPriorityPutMutation(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: listExecutionsApiV1AdminExecutionsGetQueryKey() }),
}));
```

`src/lib/query-client.ts` holds the one client, provided by the root layout. It retries a query twice on a network error or a 5xx, never a mutation, and shows failures through its cache handlers. Use `isPending` for first-load spinners and `isFetching` for refresh buttons. Outside components, use `queryClient.query(options)`; inside, a form starts over from its query data whenever that changes (see the settings pages) and saves through a mutation that calls `setQueryData`.

## Frontend: Error Handling & API Interceptors

The generated client throws the API's error body, the generated `ErrorResponse`, which carries the status. The error interceptor in `src/lib/api-interceptors.ts` only fills in the failures without one: a body that isn't an `ErrorResponse`, like a proxy's error page, becomes `{status, detail: "HTTP <status>"}`, and no response at all becomes status 0. `ErrorResponse` is registered as TanStack Query's `defaultError`, so `query.error`, `mutation.error` and the cache handlers are typed. The query client's cache `onError` then calls `showApiError`, once a query has used up its retries:

| Status | Action |
|--------|--------|
| 401 | If someone was signed in: warning toast "Session expired. Please log in again.", empties the query cache and calls `refreshAll()`, so a protected page's guard goes to `/login?redirect=<path>`. A visitor's 401 does nothing |
| 403 | Toast error "Access denied." |
| 422 | Toast error "Validation error: ..." with the formatted field errors |
| 423 | Toast warning (account locked) |
| 429 | Toast warning "Too many requests. Please slow down." |
| 500+ | Toast error "Server error. Please try again later." |
| Other 4xx | Toast error with the response `detail` |
| 0 (no response) | Toast error "Network error. Check your connection." |

Mutations with `meta: { inlineErrors: true }` (the login and register forms) skip only the 401, network and other-4xx handling and show `mutation.error.detail` under the form; 403, 422, 423, 429 and 5xx still toast. The request interceptor copies the readable `csrf_token` cookie into `X-CSRF-Token` on every non-GET request.

**Do not add try/catch around API calls**; the cache handlers do the display. To react to one specific failure, pass `onError` to `mutate` (the editor turns a 404 on update into a create). One kind of catch is fine: `.catch(() => null)` on an awaited `queryClient.query()` or `mutateAsync()` that only needs to know whether it worked (the admin detail modals, the editor's execution start), since the cache handler has already shown the error.

## Frontend: Logging

The frontend logs through LogTape, and nothing else: ESLint's `no-console` rejects `console.*` in `src/`. `init` in `src/hooks.client.ts` configures it once: every build sends every record to the collector through LogTape's OpenTelemetry sink, the way the backend sends its logs, and nothing goes to the browser console. Loki labels the lines `service_name="browser"`, and the collector's `filter/browser` decides what's dropped: below `warning` when `ENVIRONMENT` is `production`, nothing anywhere else. `init` also logs uncaught errors and unhandled rejections from window listeners. Each module takes its own logger and writes a sentence whose `{placeholders}` name every value it passes, so a line reads on its own:

```typescript
import { getLogger } from '@logtape/logtape';

const log = getLogger(['integr8scode', 'notifications']);
log.warning('Notification stream lost its connection: {error}', { error });
```

- The category is `['integr8scode', area]`; the areas today are `app`, `auth`, `api`, `editor`, `notifications` and `replay`
- Values go in the properties, never into the message string, the same rule as the backend's structlog
- `error` is for something broken (a 5xx, no response, a stream handler that threw) and fires the error-lines alert, `warning` for a degraded state the app recovers from (a dropped SSE connection), `debug` for what the user already sees in a toast or a form (a 4xx)
- Unit tests leave LogTape unconfigured, so it drops every record and no test silences the console. A test that checks a log line calls `captureLogs()` from `#test/test-utils.ts` and asserts on the records

## Frontend: Session

There's no auth store. The root `+layout.ts` load asks `/api/v1/auth/me` before any page renders and returns `{ user }`, the generated `UserResponse` or `null`; `App.PageData` in `src/app.d.ts` types it. It calls the generated SDK function without `throwOnError`, so a 401 comes back as "nobody is signed in" instead of reaching the query client's 401 handler.

- Components read `page.data.user` from `$app/state`; a layout reads its `data` prop. In markup, `{#if page.data.user}{@const user = page.data.user}` keeps the narrowing inside snippets
- The `(auth)` and admin layout loads get the user from `await parent()` and `redirect()` a visitor to `/login?redirect=<path>`; they return the user, so pages under them read it as non-null. Components under them don't check for a signed-in user again
- Login calls `goto(target, { refreshAll: true })`, which reruns the root load; the target comes from `?redirect` through `match()`. Logout and an expired session call `queryClient.clear()` first, so nothing the previous user loaded shows to the next one
- The CSRF header comes from the `csrf_token` cookie at request time, so nothing stores the token

## Frontend: Routing

SvelteKit's filesystem router: a page is `src/routes/<path>/+page.svelte`, and the root `+layout.ts` sets `ssr = false`, so it's a client-rendered SPA served through adapter-static's `200.html` fallback. Guards are `load` functions, which run before the page mounts:

```typescript
// src/routes/(auth)/+layout.ts guards /editor, /settings, /notifications; admin/+layout.ts also checks the role
export const load: LayoutLoad = async ({ parent, url }) => {
    const { user } = await parent();
    if (!user) redirect(307, `${resolve('/login')}?${new URLSearchParams({ redirect: url.pathname + url.search })}`);
    return { user };
};
```

Navigation: links and `goto()` take a path from `resolve()` in `$app/paths` (`<a href={resolve('/admin/users')}>`, `goto(resolve('/login'))`), which checks it against the routes. A route in a group goes by its route ID, so the editor is `resolve('/(auth)/editor')`. A path known only at runtime, like a notification's `action_url` or the login page's `?redirect`, goes through `match()` first, which returns null for an API path or another site. A link nginx serves, like `/grafana`, carries `rel="external"`. `page` from `$app/state` gives the current URL. Page titles go in `<svelte:head>` as `<title>Page - Integr8sCode</title>`. Errors while loading or rendering show `src/routes/+error.svelte`.

## Frontend: Overlays

Dialogs, menus, popovers and selects come from bits-ui, imported from npm and styled with our own Tailwind classes; don't copy component source into the repo and don't hand-roll click-outside or arrow-key handling. Dialogs go through `#components/Modal.svelte`, which wraps `Dialog` and keeps the `open`, `title`, `onClose`, `size`, `children` and `footer` props. Menu, popover and select content renders in a `Portal` with `class="floating-panel"`, and each item gets `class="floating-item"` (both in `styles/components.css`). A menu item that navigates renders an `<a href>` through its `child` snippet.

Tooltips use bits-ui `Tooltip` with `class="tooltip-content"`; the root layout holds the one `Tooltip.Provider`, and `renderWithQueryClient` adds it in tests. Elements look right without classes. `body` sets the text color, borders default to the `border` token, and the base layer in `app.css` styles `h1`, `h2`, `label`, inputs, selects, checkboxes and formsnap's error list and descriptions, so a class on one of them is an override, never a restatement. A structure several components repeat has one class in `styles/components.css`: `.btn-*`, `.badge-*`, `.card`, `.alert-*`, `.form-*-standard`, `.page` (a page's content column, with a `max-w-*` beside it), `.field` (a label over its control and errors), `.details` (a label and value list), `.facts` (small labels over values), `.stat` (a labelled number in a card), `.link` (a link in running text; other anchors take their parent's color), `.link-list` (links that turn the accent color on hover) and `.menu-link`, plus the `section-label` utility for the small uppercase heading over a group. Long text uses the typography plugin's `prose`, which takes its colors from the tokens. Page-only rules go in `styles/pages.css`, and anything used once stays as utilities in the markup. Repeated markup inside one file is a loop or a snippet, not copies.

Colors come only from the tokens in `app.css`: `page`, `surface`, `sidebar`, `muted`, `fg`, `fg-muted`, `fg-subtle`, `border`, `border-input`, `ring`, `accent`, `success`, `warning`, `danger`, `info`, `purple`, `indigo`, `orange` (the last seven with a `-soft` fill), `code`, `backdrop`, and the fixed fills `primary`, `secondary`, `danger-solid` and `tooltip`. Each token switches with `.dark` by itself, so never write a `dark:` variant, and never a raw palette color like `text-red-600`; ESLint rejects both. Borders default to `border`, and text inherits `fg` from `body`.

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

Markers registered in pyproject.toml: `unit`, `e2e`, `grafana_contract` (CI selects the contract tests with it). pytest-xdist adds `xdist_group`. No `@pytest.mark.asyncio`: `asyncio_mode = "auto"` covers it.

Unit tests build documents through their constructors, with no MongoDB: the session fixture `beanie_without_server` in `tests/unit/conftest.py` runs `init_beanie` on a mocked database.

`asyncio_mode = "auto"`, so a test is `async def` when it awaits and a plain `def` otherwise; about a quarter of the suite is sync. Key fixtures: `test_settings`, `app`, `client`, `redis_client`, `test_user`, `test_admin`, `another_user` (the last three are logged-in `httpx2.AsyncClient`s with the CSRF header set), and in e2e one fixture per service or repository (`execution_service`, `execution_repository`, `notification_service`, ...). A test names what it needs as parameters; it doesn't call `scope.get` itself.

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
    assert response.json()["detail"].startswith("Admin access required")
```

SSE routes need a streaming transport, because `httpx2.ASGITransport` waits for the whole body. Use `streaming_client(app, user)` from `tests/e2e/conftest.py` (built on its `StreamingASGITransport`) and read events with httpx2's `client.sse()`:

```python
async with (
    streaming_client(app, test_user) as client,
    client.sse("/api/v1/events/notifications/stream") as source,
):
    assert source.response.status_code == 200
```

Isolation: every xdist process, the API it runs and the real `worker` container share one MongoDB, one Redis database and one Kafka, so tests isolate by unique ids (uuid usernames, keys and Redis prefixes, fresh executions) and never by separate databases. Rules that keep the parallel run race-free:
- System settings are global and every process reads them, so tests change only `lockout_duration_minutes`, starting from the current settings; the two settings files share `xdist_group("system_settings")` so they don't race each other over the one document. That is the only xdist group
- Wait on what the producer stored, not on Redis pub/sub: `wait_for_event(execution_id, *types)` polls the events collection, which the producer writes before it publishes, so an event that happened first still counts
- A test that needs an execution row and not a pod uses `store_execution` (or the repository), since real executions share the global concurrency limit
- Anything a test leaves in a shared place that the worker acts on (DLQ rows) is removed by the fixture that created it, and a test that schedules a real replay picks events no consumer acts on (a stored `user_logged_in`), since the worker sends them to Kafka

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
- `vitest.setup.ts` already mocks `#lib/api/sdk.gen.ts` (SDK functions only; enums, Zod schemas, the client and the TanStack options stay real, and the options call the mocks), `initializeApiInterceptors` (so no toast handler is set), `svelte-sonner`, `$app/navigation`, `match` from `$app/paths` (a test sets the route it returns) and `page` from `$app/state`, which is the `$state` stand-in in `#test/page.svelte.ts`. Before every test it starts a fresh fake clock that moves with real time, clears `localStorage`, resets that stand-in (signed out, on `/`), clears the query cache and seeds faker. A test signs in with `page.data.user = fakeUserResponse()`; override a mock per file with `vi.mock`, and spread `importOriginal()` into a `#lib/api/index.ts` or `#lib/formatters.ts` factory so the real exports stay available
- bits-ui content renders in a portal, so query it through `screen` or `document.body`, not the render container. happy-dom gives every element a 0x0 box, so outside clicks can't be tested there; cover them in Playwright
- Fixtures come from the generated Faker factories in `#lib/api/@faker-js/faker.gen.ts` (`fakeUserResponse()` and one per schema), with the values a test depends on spread over them, never a local copy of an API type or an `as any`. The setup seeds faker before every test, so fakes repeat from run to run but shift when the spec changes: set every field the test asserts on. API calls are mocked at the SDK functions, so the MSW plugin isn't used; `mockApi(fn).ok(data)` takes the data type from `fn`'s generated return type, and `mockStreamEvents(fn, ...events)` feeds an SSE function
- Components that run queries render with `renderWithQueryClient(Component, props)`; state that builds queries outside a component (the editor's execution state) is created with `createInQueryContext(factory)`. Both come from `#test/test-utils.ts`. `mockApi(fn).err()` rejects when the call passes `throwOnError`, as the generated options do, so check SDK calls with `expect.objectContaining`. `err()` takes an `ErrorResponse`, so give it the status the test is about; the query client retries 0 and 5xx, so a failed-load test that shouldn't wait uses a 4xx
- Before each test the config resets every mock to the implementation it was created with, restores spies and undoes `vi.stubGlobal`, in a run pinned to UTC, so a test sets up only what it needs and cleans up nothing
- `await tick()` after render, `waitFor()` for async state
- Coverage thresholds: statements 92, branches 76, functions 90, lines 92; the generated client (`src/lib/api/`) is excluded

### E2E (Playwright)
- Chromium only, base URL `https://localhost:5001`, `ignoreHTTPSErrors: true` (self-signed certs), `timeout: 10_000`, `expect.timeout: 3_000`, `test.slow()` for a test that waits for a pod. In CI one retry, and `failOnFlakyTests` fails a test that passed only on retry
- Run through npm scripts: `npm run test:e2e:deps` and `npm run test:e2e:browsers` once, then `npm run test:e2e` against the compose stack on :5001 (`npm run dev` can't reach the API from the host)
- `frontend/e2e/fixtures.ts` registers one account per worker through the API and signs in the seeded `admin` (password from `ADMIN_USER_PASSWORD`, default `admin123`). Each test gets a fresh context: `page` (guest), `userPage` or `adminPage`; `api` is a client signed in as the worker's user and `execution` starts an execution through it
- Specs are flat `test()` calls with no `describe` wrappers or helpers defined inside functions. Assert with retrying `expect`, never `waitForTimeout` or a polling loop; hold a request with `page.route(url, holdRequest)` to see a loading state. Labels come from `fieldTitle` and option lists from the generated enums and schemas
- The backend container seeds the users (`scripts/seed_users.py`) before gunicorn starts; rerun it with `docker compose exec backend python -m scripts.seed_users`. For manual checks log in as `user` / `user123` or `admin` / `admin123`

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

On GitHub every check above is a job of `.github/workflows/ci.yml` that runs only when its files changed (`dorny/paths-filter`), and `All checks pass` (`re-actors/alls-green`) is the one required check on `main`, with no bypass for anyone. A new CI job goes into that job's `needs` and `allowed-skips`. Open a PR with auto-merge on (`gh pr merge --auto --squash`); a stack from `gh stack` lands with `gh stack merge` once every PR in it passes, since auto-merge doesn't cover stacks yet.

CI also runs the backend E2E suite and Playwright against a k3s stack, plus bandit and image scans. The grimp check (`backend/scripts/check_orphan_modules.py`) fails on any module in `app` that no other module imports. It skips the two entry points, `app.main` and `app.worker`, and `__init__.py` files that hold nothing but a docstring.

## Security Constraints

- K8s executor pods: non-root (uid 1000), read-only root filesystem, all capabilities dropped, no privilege escalation, `seccomp: RuntimeDefault`, `automountServiceAccountToken: false`
- NetworkPolicy: the k8s worker applies `executor-deny-all`, which denies all ingress and egress for executor pods
- Passwords: bcrypt via pwdlib (`PasswordHash((BcryptHasher(rounds=settings.BCRYPT_ROUNDS),))`)
- Login lockout after `max_login_attempts` failures (default 5, for 15 minutes), configurable in admin system settings
- Request size limit enforced by ASGI middleware (streams the body and rejects before the full payload is in memory; default 10MB)
- Rate limiting: Redis-backed, keyed by the user id of a valid access token (the middleware verifies it, since it runs before auth) or else by client IP, and it fails open when Redis errors. Default rules per 60s: execution 10, auth 20, admin 100, sse 5, websocket 5, api 60. Login, register, logout and `/api/v1/health/` skip the middleware
- CSRF: double-submit cookie pattern. `access_token` (httpOnly) plus `csrf_token` (readable) cookies, and the `X-CSRF-Token` header is required for POST, PUT, PATCH and DELETE. Login, register and unauthenticated requests are exempt
- Secrets are `SecretStr`: the Settings secrets, passwords in request schemas, `hashed_password` and the session tokens in `LoginResult`. They print as `**********` in logs, reprs and errors at any depth, and code that needs the value calls `.get_secret_value()`. A new secret field gets the type, not a log rule; the regex sanitizer in `app/core/logging.py` still redacts plain strings and third-party records
- Never log user-controlled data via string interpolation; always use structured keyword args
