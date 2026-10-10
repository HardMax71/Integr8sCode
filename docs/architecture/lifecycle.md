# Service lifecycle

Services don't manage their own lifecycle. They get their dependencies through Dishka constructors and expose plain async methods, with no `start()`, `stop()` or background task of their own. Whatever needs starting and stopping is owned by the process entry point: the FastAPI lifespan in `app/core/dishka_lifespan.py` for the API, and `backend/workers/run_*.py` for each worker.

That leaves a short list of things with a lifecycle. The Kafka broker needs `start()` and `stop()`. APScheduler instances need `start()` and `shutdown()`. The Redis client and the Kubernetes `ApiClient` are async generator providers in `app/core/providers.py`, so `container.close()` runs their teardown (`aclose()` and `close()`). The one service that breaks the rule is `EventReplayService`, which creates an `AsyncIOScheduler` per replay session in `start_session` and shuts it down when the session finishes or is cancelled.

`BrokerProvider` creates the `KafkaBroker` but never starts it. Subscribers and the Dishka integration have to be registered on an unstarted broker, so the entry point does that first and starts the broker afterwards.

## API process

The container is built in `create_app()`. The lifespan then does the rest, in this order:

1. Connect a tz-aware `AsyncMongoClient` and run `init_beanie` over `ALL_DOCUMENTS`.
2. Resolve the `Tracer` and instrument FastAPI with OpenTelemetry, skipping health, metrics and docs URLs.
3. Get the broker, register the `sse-bridge-pool` and `notification-service` subscribers, and call `setup_dishka_faststream`.
4. Start the broker.
5. Start an `AsyncIOScheduler` that runs `NotificationScheduler.process_due_notifications` every 15 seconds.

On shutdown it stops the scheduler, then the broker, then closes the container. `broker.stop()` waits up to `KAFKA_GRACEFUL_TIMEOUT` (15 seconds by default) for running handlers, and Redis is still open while it does.

gunicorn runs the API with `WEB_CONCURRENCY` workers (2 by default), and each one runs its own lifespan. That means each has its own broker connection, its own notification scheduler and its own in-memory replay sessions.

## Workers

All six workers follow the same shape. Each loads `Settings(override_path="config.<worker>.toml")`, sets up logging, runs `init_beanie`, builds its own container with `create_<worker>_container`, registers its subscribers if it has any, calls `setup_dishka`, and then blocks on `FastStream(broker, on_startup=[...], after_shutdown=[container.close]).run()`.

FastStream 0.7 runs `on_startup` hooks before it starts the broker and `after_startup` hooks after. The same goes for shutdown: `on_shutdown` runs before `broker.stop()` and `after_shutdown` after it. Startup work happens before the broker connects. A worker with a scheduler stops it in `on_shutdown`, and every worker closes its container in `after_shutdown`, so Redis and the Kubernetes client stay open until the broker has drained its handlers.

| Worker | Subscribers | Startup work | Shutdown |
|--------|-------------|--------------|----------|
| k8s-worker | `create_pod_command`, `delete_pod_command` | `ensure_namespace_security()` and `ensure_image_pre_puller_daemonset()` | `container.close` |
| pod-monitor | none | APScheduler runs the watch cycle every 5s | scheduler, then container |
| result-processor | `execution_completed`, `execution_failed`, `execution_timeout` | none | `container.close` |
| saga-orchestrator | `execution_requested`, plus completed, failed, timeout and cancelled | APScheduler runs `check_timeouts` every 30s and `try_schedule_from_queue` every 10s | scheduler, then container |
| dlq-processor | none | APScheduler runs `process_monitoring_cycle` every 10s | scheduler, then container |
| event-replay | none | APScheduler runs `cleanup_old_sessions(older_than_hours=48)` every 6 hours | scheduler, then container |

The pod monitor's watch cycle calls `watch_pod_events()`. On a 410 from the API server it resets the resource version so the next cycle starts a fresh watch, and every error is counted in the watch error and reconnect metrics.

Replay sessions are created and driven through the API's replay routes, so they live in the API process. The event-replay worker never holds a session in memory, and its cleanup job only deletes terminal sessions older than 48 hours from MongoDB.

## Adding a service or worker

A new service is a plain class with constructor dependencies and async methods. If it needs periodic work, add an APScheduler job in the entry point that owns it and keep the service unaware of scheduling.

A new worker copies one of the `run_*.py` files. Give it a `config.<worker>.toml`, a container factory in `app/core/container.py`, and a `register_*_subscriber` function in `app/events/handlers.py` if it consumes events. Register subscribers and call `setup_dishka` before `app.run()`. Stop schedulers in `on_shutdown` and close the container in `after_shutdown`, so nothing the handlers use closes before the broker stops.
