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

All six workers share a common bootstrap sequence: load settings, init logger, connect to MongoDB via Beanie, create a Dishka DI container, retrieve the Kafka broker, wire up Dishka, and run FastStream. The shared `run_worker()` function in `workers/bootstrap.py` handles this boilerplate. Each worker only provides its unique configuration and optional hooks:

```python
from workers.bootstrap import run_worker

def main() -> None:
    run_worker(
        worker_name="ResultProcessor",
        config_override="config.result-processor.toml",
        container_factory=create_result_processor_container,
        register_handlers=register_result_processor_subscriber,
    )
```

Workers that need custom startup logic (APScheduler jobs, K8s pre-warming) pass `on_startup` and `on_shutdown` callbacks:

```python
async def _on_startup(container, broker, logger) -> None:
    service = await container.get(SomeService)
    scheduler.add_job(service.periodic_task, trigger="interval", seconds=10, ...)
    scheduler.start()

async def _on_shutdown() -> None:
    scheduler.shutdown(wait=False)

run_worker(..., on_startup=_on_startup, on_shutdown=_on_shutdown)
```

FastStream calls `on_startup` after the broker connects and `on_shutdown` when the process receives a signal. The worker blocks on `app.run()` until termination. The container is always closed last (appended automatically by `run_worker`).

All six workers follow this pattern:

| Worker | Startup hook | Has APScheduler |
|--------|-------------|-----------------|
| k8s-worker | Pre-pull daemonset, namespace security | No |
| pod-monitor | Start watch loop | Yes |
| result-processor | — | No |
| saga-orchestrator | Start saga scheduler | Yes |
| dlq-processor | Start monitoring cycle | Yes |
| event-replay | Start replay scheduler | Yes |

Workers without startup work pass only `register_handlers` and rely on `run_worker`'s default shutdown (container close).

## Why stateless services

Earlier iterations had services that started themselves in constructors, or DI providers that managed `start`/`stop`. That scattered lifecycle logic across multiple layers and made shutdown order fragile.

The current approach pushes all lifecycle concerns to the edges (lifespan and worker entrypoints) and keeps services as pure handlers. Benefits:

- **Testable**: instantiate a service, call a method, assert results. No setup/teardown ceremony.
- **Predictable shutdown**: one place per process owns the teardown sequence.
- **No hidden state**: services don't hold background tasks or connections. The broker and scheduler do, and they're managed explicitly.

## Building new services

Write a plain class that takes its dependencies in `__init__` via Dishka. Expose async methods. Don't start background work in the constructor — if the service needs a periodic job, let the worker entrypoint set up APScheduler and register the method as a job. The service itself stays unaware of scheduling.

## Building new workers

Use the shared `run_worker()` function from `workers/bootstrap.py`:

1. Create a container factory in `app/core/container.py` for the new worker
2. Create a `config.<worker-name>.toml` override file
3. Register Kafka subscriber handlers and/or define `on_startup` / `on_shutdown` callbacks for APScheduler or other setup as needed
4. Call `run_worker()` with the worker name, config override, container factory, and optional hooks

See any existing `workers/run_*.py` for a working example. The simplest is `run_result_processor.py` (no startup hooks), the most complex is `run_pod_monitor.py` (APScheduler + K8s watch loop).
