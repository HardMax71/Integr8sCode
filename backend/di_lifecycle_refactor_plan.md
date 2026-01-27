# Backend DI Lifecycle Refactor Plan

## Goals
- Push all service lifecycle management into Dishka providers; no ad-hoc threads, `is_running` flags, or manual `__aenter__/__aexit__`, `_on_start` / `_on_stop` hooks.
- Keep **zero lifecycle helper files or task-group utilities** in app code; Dishka provider primitives alone manage ownership, and container close is the only shutdown signal.
- Simplify worker entrypoints and FastAPI startup so shutting down the DI container is the only teardown required.

## Current Pain Points (code refs)
- `app/core/lifecycle.py` mixes lifecycle concerns into every long-running service and leaks `is_running` flags across the codebase.
- Kafka-facing services (`events/core/consumer.py`, `events/core/producer.py`, `events/event_store_consumer.py`, `services/result_processor/processor.py`, `services/k8s_worker/worker.py`, `services/coordinator/coordinator.py`, `services/sse/kafka_redis_bridge.py`, `services/notification_service.py`, `dlq/manager.py`) start background loops via `asyncio.create_task` and manage stop signals manually.
- FastAPI lifespan (`app/core/dishka_lifespan.py`) manually enters/starts multiple services and stacks callbacks; workers use `while service.is_running` loops (e.g., `workers/run_saga_orchestrator.py`).
- `app/core/adaptive_sampling.py` spins a raw thread for periodic work.
- `EventBusManager` caches an `EventBus` started via `__aenter__`, duplicating lifecycle logic.

## Target Architecture (Dishka-centric)
- Use Dishka `@provide` async-generator providers directly—no extra lifecycle helper modules. Providers must **not** call `start/stop/__aenter__/__aexit__`; objects are usable immediately after construction and simply released when the container closes.
- Keep services as pure orchestrators/handlers that assume dependencies are already constructed; no lifecycle methods (`start`, `stop`, `aclose`, `__aenter__`, `__aexit__`, `is_running`).
- FastAPI lifecycle only needs to create/close the container; bootstrap work (schema registry init, Beanie init, rate-limit seeding) runs inside an `APP`-scoped provider without explicit start/stop calls.
- Worker entrypoints resolve services (already constructed by providers), then block on a shutdown event; container.close() just releases references—no service teardown calls.

## Step-by-Step Refactor
1) **Inline provider construction (no helper files, no start/stop)**
   - Keep everything inside existing provider classes; do not add `core/di/*` helper modules.
   - Providers construct dependencies once and yield them; **no start/stop or context-manager calls** inside providers. Objects must be drop-safe when the container releases them.

2) **Retire `LifecycleEnabled`**
   - Remove the base class and delete `is_running` state from all services.
   - Convert services to plain classes whose constructors accept already-started collaborators (producer, dispatcher, repositories, etc.).
   - Where a class only wrapped start/stop (e.g., `UnifiedProducer`, `UnifiedConsumer`), replace with lightweight functions or data classes plus provider-managed runners.

3) **Kafka-facing services → passive, no lifecycle**
   - Event ingestors (`EventStoreConsumer`, `ResultProcessor`, `NotificationService`, `SSEKafkaRedisBridge`, `DLQManager`, `ExecutionCoordinator`, `KubernetesWorker`, `SagaOrchestrator`, `PodMonitor`) become passive components: construction wires handlers/clients, but there is **no start/stop**. Message handling is invoked explicitly by callers (per-request or explicit trigger), not via background loops.
   - Delete `_batch_task`, `_scheduling_task`, `_process_task`, and any `asyncio.create_task` usage. No runners, no background scheduling, no threads/processes.

4) **FastAPI bootstrap simplification**
   - Remove custom lifespan entirely; rely on FastAPI default lifecycle.
   - Perform one-time bootstrap (schemas, Beanie, rate limits, tracing/metrics wiring) directly in `main.py` before constructing the app object and DI container. No dedicated provider or lifespan hook.
   - Wiring stays declarative in `main.py`; providers stay free of bootstrap side-effects.

5) **Worker entrypoints overhaul**
   - Use signal-driven shutdown only: install handlers, wait on shutdown event, then rely on Dishka to close the container (no explicit teardown). Avoid polling loops, task groups, runners, lifecycle files.
   - Providers should be sync where possible; prefer simple constructors over async generators so container cleanup is automatic and implicit.
   - Each worker script builds settings → container, resolves the needed service (already constructed by its provider), logs readiness, then waits on the shutdown event.

6) **Adaptive sampling & other threads**
   - Replace `AdaptiveSampler` thread with on-demand, stateless computation (pure function or cached calculator). No background loop, no thread, no task group.
   - Audit and remove any `threading.Thread` or `multiprocessing` usage; prefer synchronous or explicitly awaited calls executed by the caller.

7) **Testing & migration**
   - Update unit tests to drop assertions around `is_running` and context-manager behavior; add tests that closing the DI container cancels consumer loops and flushes Kafka commits.
   - Add a narrow integration test that spins an APP-scoped container with a fake consumer to verify provider-managed shutdown.
   - Keep `uv run pytest` as the execution path; prefer `PYTEST_ADDOPTS=` override to disable xdist when debugging lifecycle issues locally.

## Risks / Open Questions
- Kafka libraries typically expect explicit `start/stop`; shifting to construct-and-drop may require swapping implementations (e.g., per-call producer/consumer) to avoid leaks.
- Some startup routines (Kubernetes config load) are blocking; may still need threadpool execution even without explicit lifecycle.
- Need to ensure Dishka container close is called in all entrypoints so provider objects are released.

## Definition of Done
- No class in `app/` inherits `LifecycleEnabled`; the file is removed.
- No service exposes `is_running` or `__aenter__/__aexit__`; lifecycle lives exclusively in providers.
- FastAPI and worker entrypoints use container close as the sole shutdown hook.
- No background loops/tasks/threads/processes; services do work only when explicitly invoked.
- Unit and targeted integration tests pass under `uv run pytest` with minimal/no external dependencies.
