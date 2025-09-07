Integr8s Backend Services — Human-Friendly Overview

Purpose
- This document explains what lives under `backend/app/services/`, what each service does, and how the separately deployed workers (with their own Dockerfiles) work end‑to‑end. It is written for engineers joining the project who want a fast, pragmatic mental model before reading code.

High‑Level Architecture
- API (FastAPI) receives user requests (auth, execute, events, scripts, settings).
- Coordinator accepts validated execution requests and enqueues them (Kafka) with metadata and idempotency guards.
- Saga Orchestrator drives stateful execution via events (Creation → Run → Completion/Timeout/Failure) and publishes commands to the K8s Worker.
- K8s Worker builds and creates per‑execution pods and supporting ConfigMaps. Network isolation is enforced at cluster level via Cilium policy; pods are hardened (non‑root, read‑only, no SA token, DNS off).
- Pod Monitor watches K8s and translates pod phases and logs into domain events.
- Result Processor consumes completion/failure/timeout events, updates DB, cleans resources.
- SSE Router fans execution events out to connected clients.
- DLQ Processor and Event Replay support reliability and investigations.

Key Event Streams (Kafka)
- EXECUTION_EVENTS: lifecycle updates (queued, started, running, events, cancelled).
- EXECUTION_COMPLETED / EXECUTION_FAILED / EXECUTION_TIMEOUT: terminal states with outputs.
- SAGA_COMMANDS: saga → worker commands (create/delete pod).
- DLQ: dead‑lettered messages for later processing.

Directory Tour: `backend/app/services/`

1) coordinator/
- QueueManager: In‑memory view of pending executions with priorities, aging, and backpressure. It does not own metrics for queue depth (centralized in coordinator metrics) and does not publish commands directly — it emits events for the Saga/Orchestrator to process.
- Why it matters: Provides fairness, limits, and stale‑job cleanup in one place. Prevents double publications and bouncing queue depth.

2) saga/
- ExecutionSaga: Encodes the multi‑step execution flow (receive request → create pod command → observe pod outcomes → commit result). Publishes only when configured to avoid duplicate CreatePodCommandEvent.
- Saga Orchestrator: Subscribes to EXECUTION events; reconstructs sagas; issues SAGA_COMMANDS to the worker. Goals: idempotency across restarts, clean compensation (e.g., delete pod on failure), and avoiding duplicate side‑effects.

3) k8s_worker/
- worker.py: Long‑running service that consumes SAGA_COMMANDS and creates per‑execution resources:
  - ConfigMap for script and entrypoint.
  - Pod manifest with hardened security context and volume layout.
  - It no longer creates per‑execution NetworkPolicies. Network isolation is managed by a static Cilium policy in the target namespace.
  - Refuses to run in the `default` namespace to avoid policy gaps.
- pod_builder.py: Produces ConfigMaps and V1Pod specs:
  - Non‑root, read‑only root FS; drop ALL capabilities; seccomp RuntimeDefault; DNS disabled; no service links/tokens.
  - Read‑only mounts for ConfigMaps; memory‑backed temporary/output volumes are optional and capped.

4) pod_monitor/
- monitor.py + event_mapper.py: Watches K8s Pod/Container status, maps them into domain events with helpful metadata (exit codes, failure reasons, stdout/stderr slices), and publishes into EXECUTION_EVENTS.
- Why: This decouples “what the cluster did” from “what the system emits” so clients always see consistent event shapes.

5) result_processor/
- processor.py: Consumes terminal events (completed/failed/timeout), persists results, normalizes error types, and always records metrics (errors by type). Also triggers cleanup.
- resource_cleaner.py: Deletes the per‑execution pod and ConfigMap. NetworkPolicies are no longer deleted here — isolation is cluster‑level static policy.

6) sse/
- partitioned_event_router.py + sse_shutdown_manager.py: Binds Kafka consumers to execution IDs and buffers events per execution for Server‑Sent Events streams with graceful shutdown.
- Why: Keeps SSE robust under load, isolates a slow client from blocking others, and implements backpressure.

7) execution_service.py
- The façade used by API routes. Validates script/lang/version, consults the runtime registry, constructs idempotent requests, and emits initial “queued/requested” events.

8) event_service.py / kafka_event_service.py / event_bus.py
- Read/write/fan‑out events in a uniform way with mappers. kafka_event_service centralizes production (headers, correlation IDs, error handling).

9) replay_service.py / event_replay/
- Tools and workers for replaying historical events into the system to debug, recompute state, or backfill projections.

10) notification_service.py
- Sends/stores notifications and exposes subscription management. Integrates with metrics and optional channels (webhook, Slack) with delivery measurements and retries.

11) user_settings_service.py
- Provides a CRUD + event‑sourced history for user settings with a small in‑proc cache and helpers to compute “what changed”.

12) rate_limit_service.py
- Redis‑backed sliding window / token bucket implementation with dynamic configuration per endpoint group, user overrides, and IP fallback. Safe failure mode (“fail open”) with explicit metrics when Redis is unavailable.

13) idempotency/
- Middleware and wrappers to make Kafka consumption idempotent (content‑hash or custom keys). Used for SAGA_COMMANDS to avoid duplicate pod creation.

14) saga_service.py
- Read‑model access for saga state and guardrails (e.g., enforcing access control on saga inspection routes).

15) saved_script_service.py
- CRUD for saved scripts with ownership checks and validations; integrates with the API for “run saved script” flows.


Separately Deployed Workers (Dockerfiles in backend/workers/)

These services run outside the API container for isolation and horizontal scaling. Each has a small `run_*.py` entry and a dedicated Dockerfile.

1) Saga Orchestrator (Dockerfile.saga_orchestrator)
- Purpose: Stateful choreographer for execution life‑cycle.
- Subscribes: EXECUTION_EVENTS (and internal saga topics as needed).
- Publishes: SAGA_COMMANDS (CreatePodCommandEvent, DeletePodCommandEvent).
- Idempotency: Rebuilds saga state from events; issues commands only when transitions are valid and not yet executed.
- Failure handling: On failures/timeouts/cancellations, publishes compensating commands (delete pod) and finalizes saga.

Event schema (simplified)
- CreatePodCommandEvent: { execution_id, script, runtime_image, runtime_command, runtime_filename, timeout, resources, metadata{ user_id, correlation_id } }
- Execution*Event: { execution_id, type, timestamps, stdout/stderr slices, resource_usage, error_type? }

2) K8s Worker (Dockerfile.k8s_worker)
- Purpose: Materializes saga commands into K8s resources.
- Consumes: SAGA_COMMANDS.
- Creates: ConfigMap (script, entrypoint), Pod (hardened).
- Security: No per‑exec NP; relies on CiliumNetworkPolicy (deny‑all) applied to the namespace. Pod spec disables DNS, drops caps, runs non‑root, no SA token.
- Publishes: PodCreated / ExecutionStarted events (and errors when creation fails).

3) Result Processor (Dockerfile.result_processor)
- Purpose: Persist terminal execution outcomes, update metrics, trigger cleanup.
- Consumes: EXECUTION_COMPLETED / EXECUTION_FAILED / EXECUTION_TIMEOUT.
- Writes: DB records (status, outputs, errors, usage) and metrics (errors by type, durations).
- Side‑effects: Invokes ResourceCleaner to delete pods/configmaps.

4) Pod Monitor (Dockerfile.pod_monitor)
- Purpose: Observe K8s pod state and translate to domain events.
- Watches: CoreV1 Pod events.
- Publishes: EXECUTION_EVENTS (running, container started, logs tail, etc.).
- Adds: Useful metadata and best‑effort failure analysis.

5) Coordinator (Dockerfile.coordinator)
- Purpose: Own the admission/queuing policy, set priorities, gate starts based on capacity.
- Interacts with: ExecutionService (API), Saga Orchestrator (events).
- Ensures: Queue depth metrics reflect only user requests; avoids negative values via a single owner for the counter.

6) Event Replay (Dockerfile.event_replay)
- Purpose: Re-emit stored events to debug or rebuild projections.
- Inputs: DB/event store and filters.
- Outputs: Replayed events on regular topics with provenance markers.

7) DLQ Processor (Dockerfile.dlq_processor)
- Purpose: Drain and retry dead‑lettered messages with backoff and visibility.
- Inputs: DLQ topic, retry policies.
- Outputs: Successful re‑publishes or parked messages with audit trail.

Operational Notes
- Namespace: The worker refuses to run in `default`. Use the setup script to apply the Cilium policy in a dedicated namespace and run the worker there.
- Policies: Apply `backend/k8s/policies/executor-deny-all-cnp.yaml` (or use `scripts/setup_k8s.sh <namespace>`). All executor pods are labeled `app=integr8s, component=executor` and are covered by the static deny‑all policy.
- Idempotency: Sagas and consumers use content‑hash keys by default to avoid duplicates on restarts.
- Metrics: Coordinator centralizes queue depth; Result Processor normalizes error types; Rate Limit service emits rich diagnostics even when disabled.

Common Flows (ASCII)

User → API → Coordinator → Saga Orchestrator → K8s Worker → Pod → Pod Monitor → Result Processor

1) Execute script
  POST /api/v1/execute
    → Validation → enqueue EXECUTION_REQUESTED
    → Saga: issues CreatePodCommandEvent
    → Worker: ConfigMap + Pod created
    → Pod Monitor: emits running/progress
    → Result Processor: on completion/failure/timeout → persist + cleanup

2) SSE stream
  Client subscribes → SSE Router binds to relevant topics → buffered fan‑out per execution, clean shutdown on deploys.

Troubleshooting Pointers
- “Why do I still see TCP egress?” Ensure Cilium is installed and the CNP is applied in the same namespace. The code no longer creates per‑execution NetworkPolicies; it expects cluster‑level enforcement.
- “Why do I see 422/405 in load?” That’s the monkey test fuzzing invalid or wrong endpoints. Use `--mode user` for clean runs.
- “Why do I get 599 in load?” Client timeouts due to saturation. Scale with Gunicorn workers (WEB_CONCURRENCY), and avoid TLS during load if acceptable.

