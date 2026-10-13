# Service lifecycle

Services don't manage their own lifecycle. They get their dependencies through Dishka constructors and expose plain async methods, with no `start()`, `stop()` or background task of their own. Whatever needs starting and stopping is owned by the process entry point: the FastAPI lifespan in `app/core/dishka_lifespan.py` for the API, and `app/worker.py` for the worker.

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

## Worker process

`app/worker.py` loads `Settings(override_path="config.worker.toml")`, sets up logging, runs `init_beanie`, builds its container with `create_worker_container`, registers the k8s worker, result processor and saga routers, calls `setup_dishka`, runs `start_jobs`, and then blocks on `FastStream(broker, on_shutdown=[scheduler.shutdown], after_shutdown=[container.close]).run()`.

FastStream 0.7 runs `on_shutdown` hooks before `broker.stop()` and `after_shutdown` hooks after it. `start_jobs` runs before `run()`, so the startup work happens before the broker connects; on the way out the scheduler stops before the broker drains, and the container closes last, which keeps Redis and the Kubernetes client open until the handlers are done.

`start_jobs` calls `ensure_namespace_security()` and `ensure_image_pre_puller_daemonset()`, then schedules four APScheduler jobs, each with `max_instances=1`:

| Job | Interval | Calls |
|-----|----------|-------|
| `pod_monitor_watch` | 5s | `PodMonitor.watch_cycle` |
| `saga_try_schedule` | 10s | `SagaOrchestrator.try_schedule_from_queue` |
| `saga_check_timeouts` | 30s | `SagaOrchestrator.check_timeouts` |
| `dlq_monitor_retries` | 10s | `DLQManager.process_monitoring_cycle` |

`watch_cycle` calls `watch_pod_events()`. On a 410 from the API server it resets the resource version so the next cycle starts a fresh watch, and every error that ends the cycle is counted in the watch error and reconnect metrics. An error while handling one pod event is caught inside `PodMonitor` and counted as a watch error only, and the watch carries on.

Replay sessions are created and driven through the API's replay routes, so they live in the API process. MongoDB deletes finished sessions 48 hours after they complete, through a TTL index on `completed_at`.

## Adding a service or worker

A new service is a plain class with constructor dependencies and async methods. If it needs periodic work, add an APScheduler job in the entry point that owns it and keep the service unaware of scheduling.

New background work goes into the worker rather than a new process. A consumer gets a router factory in `app/events/handlers.py` with its own `group_id`, included next to the others in `app/worker.py`, and its provider joins `create_worker_container`. A periodic job is one more entry in `start_jobs`, a method of a service the container already builds.
