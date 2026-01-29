# Services overview

This document explains what lives under `backend/app/services/`, what each service does, and how the separately deployed workers work end-to-end. It's written for engineers joining the project who want a fast mental model before reading code.

## High-level architecture

The API (FastAPI) receives user requests for auth, execute, events, scripts, and settings. The Coordinator accepts validated execution requests and enqueues them to Kafka with metadata and idempotency guards. The Saga Orchestrator drives stateful execution via events and publishes commands to the K8s Worker. The K8s Worker builds and creates per-execution pods and supporting ConfigMaps with network isolation enforced at cluster level via Cilium policy. Pod Monitor watches K8s and translates pod phases and logs into domain events. Result Processor consumes completion/failure/timeout events, updates DB, and cleans resources. SSE Router fans execution events out to connected clients. DLQ Processor and Event Replay support reliability and investigations.

## Event streams

EXECUTION_EVENTS carries lifecycle updates like queued, started, running, and cancelled. EXECUTION_COMPLETED, EXECUTION_FAILED, and EXECUTION_TIMEOUT are terminal states with outputs. SAGA_COMMANDS carries saga-to-worker commands for creating and deleting pods. DLQ holds dead-lettered messages for later processing. For more on topic design and event schemas, see [Kafka Topics](kafka-topic-architecture.md).

## Execution pipeline services

The coordinator/ module contains QueueManager which maintains an in-memory view of pending executions with priorities, aging, and backpressure. It doesn't own metrics for queue depth (that's centralized in coordinator metrics) and doesn't publish commands directly, instead emitting events for the Saga Orchestrator to process. This provides fairness, limits, and stale-job cleanup in one place while preventing double publications.

The saga/ module has ExecutionSaga which encodes the multi-step execution flow from receiving a request through creating a pod command, observing pod outcomes, and committing the result. The Saga Orchestrator subscribes to EXECUTION events, reconstructs sagas, and issues SAGA_COMMANDS to the worker with goals of idempotency across restarts, clean compensation on failure, and avoiding duplicate side-effects.

The k8s_worker/ module runs worker.py, a long-running service that consumes SAGA_COMMANDS and creates per-execution resources including ConfigMaps for script and entrypoint, and Pod manifests with hardened security context. It no longer creates per-execution NetworkPolicies since network isolation is managed by a static Cilium policy in the target namespace, and it refuses to run in the default namespace to avoid policy gaps. The pod_builder.py produces ConfigMaps and V1Pod specs with non-root user, read-only root FS, all capabilities dropped, seccomp RuntimeDefault, DNS disabled, and no service links or tokens.

The pod_monitor/ module has monitor.py and event_mapper.py which watch K8s Pod/Container status, map them into domain events with helpful metadata like exit codes, failure reasons, and stdout/stderr slices, then publish into EXECUTION_EVENTS. This decouples what the cluster did from what the system emits so clients always see consistent event shapes. See [Pod Monitor](../components/workers/pod_monitor.md) for details.

The result_processor/ module runs processor.py which consumes terminal events, persists results, normalizes error types, and always records metrics by error type. The resource_cleaner.py deletes the per-execution pod and ConfigMap after completion. See [Result Processor](../components/workers/result_processor.md) for details.

## Event and streaming services

The sse/ module contains kafka_redis_bridge.py and sse_shutdown_manager.py which bridge Kafka events to Redis channels for Server-Sent Events across workers with graceful shutdown. This keeps SSE robust under load, isolates slow clients from blocking others, and implements backpressure. See [SSE Architecture](../components/sse/sse-architecture.md) for details.

The execution_service.py is the facade used by API routes. It validates script/lang/version, consults the runtime registry, constructs idempotent requests, and emits initial queued/requested events.

The event_service.py, kafka_event_service.py, and event_bus.py handle read/write/fan-out of events in a uniform way with mappers. kafka_event_service centralizes production including headers, correlation IDs, and error handling.

The replay_service.py and event_replay/ provide tools and workers for replaying historical events into the system to debug, recompute state, or backfill projections.

## User-facing services

The notification_service.py sends and stores notifications, exposes subscription management, and integrates with metrics and optional channels like webhook and Slack with delivery measurements and retries. See [Notification Types](../operations/notification-types.md) for the notification model.

The user_settings_service.py provides CRUD plus event-sourced history for user settings with a small in-proc cache and TypeAdapter-based merging. See [User Settings Events](user-settings-events.md) for the event sourcing pattern.

The saved_script_service.py handles CRUD for saved scripts with ownership checks and validations, integrating with the API for run-saved-script flows.

## Infrastructure services

The rate_limit_service.py is a Redis-backed sliding window / token bucket implementation with dynamic configuration per endpoint group, user overrides, and IP fallback. It has a safe failure mode (fail open) with explicit metrics when Redis is unavailable.

The idempotency/ module provides `IdempotentEventDispatcher`, a subclass of `EventDispatcher` that wraps every registered handler with duplicate detection via content-hash or event-based keys. DI providers create this dispatcher for services consuming Kafka events (coordinator, k8s worker, result processor).

The saga_service.py provides read-model access for saga state and guardrails like enforcing access control on saga inspection routes.

## Deployed workers

These services run outside the API container for isolation and horizontal scaling. Each has a small run_*.py entry and a dedicated Dockerfile in backend/workers/.

The Saga Orchestrator is a stateful choreographer for execution lifecycle. It subscribes to EXECUTION_EVENTS and internal saga topics, publishes SAGA_COMMANDS (CreatePodCommandEvent, DeletePodCommandEvent), rebuilds saga state from events, and issues commands only when transitions are valid and not yet executed. On failures, timeouts, or cancellations it publishes compensating commands and finalizes the saga.

The K8s Worker materializes saga commands into K8s resources. It consumes SAGA_COMMANDS and creates ConfigMap (script, entrypoint) and Pod (hardened), relying on CiliumNetworkPolicy deny-all applied to the namespace rather than per-exec policies. Pod spec disables DNS, drops caps, runs non-root, no SA token. It publishes PodCreated and ExecutionStarted events, or errors when creation fails.

The Result Processor persists terminal execution outcomes, updates metrics, and triggers cleanup. It consumes EXECUTION_COMPLETED, EXECUTION_FAILED, EXECUTION_TIMEOUT, writes DB records for status, outputs, errors, and usage, records metrics for errors by type and durations, and invokes ResourceCleaner to delete pods and configmaps.

The Pod Monitor observes K8s pod state and translates to domain events. It watches CoreV1 Pod events and publishes EXECUTION_EVENTS for running, container started, logs tail, etc., adding useful metadata and best-effort failure analysis.

The Coordinator owns the admission/queuing policy, sets priorities, and gates starts based on capacity. It interacts with ExecutionService (API) and Saga Orchestrator (events), ensuring queue depth metrics reflect only user requests and avoiding negative values via single ownership of the counter.

The Event Replay worker re-emits stored events to debug or rebuild projections, taking DB/event store and filters as inputs and outputting replayed events on regular topics with provenance markers.

The DLQ Processor drains and retries dead-lettered messages with backoff and visibility, taking DLQ topic and retry policies as inputs and outputting successful re-publishes or parked messages with audit trail. See [Dead Letter Queue](../components/dead-letter-queue.md) for more on DLQ handling.

## Operational notes

The worker refuses to run in the default namespace. Use the setup script to apply the Cilium policy in a dedicated namespace and run the worker there. Apply `backend/k8s/policies/executor-deny-all-cnp.yaml` or use `scripts/setup_k8s.sh <namespace>`. All executor pods are labeled `app=integr8s, component=executor` and are covered by the static deny-all policy. See [Security Policies](../security/policies.md) for details on network isolation.

Sagas and consumers use content-hash keys by default to avoid duplicates on restarts. Coordinator centralizes queue depth metrics, Result Processor normalizes error types, and Rate Limit service emits rich diagnostics even when disabled.

## Common flows

The main execution flow goes: User → API → Coordinator → Saga Orchestrator → K8s Worker → Pod → Pod Monitor → Result Processor. See [Lifecycle](lifecycle.md) for the full execution state machine.

For executing a script, a POST to `/api/v1/execute` triggers validation and enqueues EXECUTION_REQUESTED. The Saga issues CreatePodCommandEvent, the Worker creates ConfigMap and Pod, Pod Monitor emits running/progress events, and Result Processor persists the outcome and triggers cleanup on completion, failure, or timeout.

For SSE streams, the client subscribes and SSE Router binds to relevant topics with buffered fan-out per execution and clean shutdown on deploys.

## Troubleshooting

If you still see TCP egress, ensure Cilium is installed and the CNP is applied in the same namespace. The code no longer creates per-execution NetworkPolicies and expects cluster-level enforcement.

If you see 422/405 in load tests, that's the monkey test fuzzing invalid or wrong endpoints. Use `--mode user` for clean runs.

If you get 599 in load tests, those are client timeouts due to saturation. Scale with Gunicorn workers (WEB_CONCURRENCY) and avoid TLS during load if acceptable.
