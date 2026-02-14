# Service lifecycle

Services in this codebase are stateless by design. They receive their dependencies through Dishka constructors and expose plain async methods — no `start()`, no `stop()`, no context manager protocol. Lifecycle management sits outside the services themselves: the FastAPI lifespan handles the API process, and FastStream callbacks handle each worker process.

This keeps services simple and testable. A service doesn't know or care how it was created or when it will be destroyed. It just does its job when called.

## How it works

Two infrastructure components actually have lifecycle: the **Kafka broker** (needs `start`/`stop`) and **APScheduler** instances (need `start`/`shutdown`). Everything else — services, repositories, the producer — is stateless and disposable.

The FastAPI lifespan and worker entrypoints each manage these two concerns in their own way, but the principle is the same: start infrastructure, yield or block, then tear down in reverse.

## FastAPI lifespan

The API process manages the broker and a notification scheduler:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ... init Beanie, register subscribers, set up Dishka ...
    await broker.start()

    notification_apscheduler = AsyncIOScheduler()
    notification_apscheduler.add_job(scheduler.process_due_notifications, ...)
    notification_apscheduler.start()

    try:
        yield
    finally:
        notification_apscheduler.shutdown(wait=False)
        await broker.stop()
        await container.close()
```

Explicit try/finally keeps teardown visible. The broker stops before the container closes, so any in-flight publishes complete before DI resources are released.

## Worker entrypoints

Workers use FastStream's `on_startup` / `on_shutdown` callbacks instead of a context manager:

```python
async def init_service() -> None:
    worker = await container.get(SomeService)
    # optional: set up APScheduler, pre-warm caches, etc.

async def shutdown() -> None:
    scheduler.shutdown(wait=False)  # if APScheduler was used
    await container.close()

app = FastStream(broker, on_startup=[init_service], on_shutdown=[shutdown])
await app.run()
```

FastStream calls `on_startup` after the broker connects and `on_shutdown` when the process receives a signal. The worker blocks on `app.run()` until termination.

All seven workers follow this pattern:

| Worker | Startup hook | Has APScheduler |
|--------|-------------|-----------------|
| coordinator | — | No |
| k8s-worker | Pre-pull daemonset | No |
| pod-monitor | Start watch loop | Yes |
| result-processor | — | No |
| saga-orchestrator | Start saga scheduler | Yes |
| dlq-processor | Start monitoring cycle | Yes |
| event-replay | Start replay scheduler | Yes |

Workers without startup work pass only `on_shutdown=[container.close]`.

## Why stateless services

Earlier iterations had services that started themselves in constructors, or DI providers that managed `start`/`stop`. That scattered lifecycle logic across multiple layers and made shutdown order fragile.

The current approach pushes all lifecycle concerns to the edges (lifespan and worker entrypoints) and keeps services as pure handlers. Benefits:

- **Testable**: instantiate a service, call a method, assert results. No setup/teardown ceremony.
- **Predictable shutdown**: one place per process owns the teardown sequence.
- **No hidden state**: services don't hold background tasks or connections. The broker and scheduler do, and they're managed explicitly.

## Building new services

Write a plain class that takes its dependencies in `__init__` via Dishka. Expose async methods. Don't start background work in the constructor — if the service needs a periodic job, let the worker entrypoint set up APScheduler and register the method as a job. The service itself stays unaware of scheduling.

## Building new workers

Follow the existing pattern in `backend/workers/`:

1. Create a `Settings` with the worker's override TOML
2. Init Beanie, create the worker's DI container, get the broker
3. Register subscribers and set up Dishka on the broker
4. Define `init_*` and `shutdown` callbacks
5. Create `FastStream(broker, on_startup=[...], on_shutdown=[...])` and call `app.run()`
