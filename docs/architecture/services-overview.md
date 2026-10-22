# Services overview

This page maps `backend/app/services/` and the worker that runs outside the API. Read it for a mental model before you open the code.

## The API's services

Route handlers get these from Dishka. They hold the business logic, talk to MongoDB through repositories and publish events through `UnifiedProducer`.

| Module | What it does |
|--------|--------------|
| `auth_service.py`, `login_lockout.py` | Login, registration, the current user from the JWT cookie, lockout after repeated failed logins. See [Authentication](authentication.md). |
| `execution_service.py` | The facade behind `/execute`. Checks the runtime registry, stores the execution, publishes `ExecutionRequestedEvent`, and publishes `ExecutionCancelledEvent` on cancel or delete. Handles the `Idempotency-Key` header. |
| `execution_queue.py` | `ExecutionQueueService`, the Redis priority queue the execution scheduler starts executions from. See [Execution Queue](execution-queue.md). |
| `execution_scheduler.py` | `ExecutionScheduler`, which starts queued executions while slots are free, cancels them and frees their slots. |
| `event_service.py` | Reading stored events. Publishing goes through `UnifiedProducer` directly. |
| `event_replay/` | `EventReplayService`, which runs admin replay sessions in the worker and sends their events to Kafka again. |
| `sse/` | `SSERedisBus` and `SSEService`. See [SSE](../components/sse/sse-architecture.md). |
| `notification_service.py` | In-app notifications for finished executions, and their delivery over SSE. |
| `user_settings_service.py` | Settings stored as events with snapshots, rebuilt on every read. See [User Settings Events](user-settings-events.md). |
| `saved_script_service.py` | CRUD for saved scripts, scoped to the owner. |
| `rate_limit_service.py` | Redis sliding window and token bucket limits per endpoint group. See [Rate Limiting](rate-limiting.md). |
| `idempotency/` | `IdempotencyManager` and its Redis repository. See [Idempotency](idempotency.md). |
| `runtime_settings.py` | `RuntimeSettingsLoader`, which reads the admin-set system settings from MongoDB, falls back to the TOML values and caches the result for 60 seconds. |
| `admin/` | Admin services for users, executions, events and system settings. |
| `k8s_worker/`, `pod_monitor/`, `result_processor/` | The services behind the worker's parts of the same name. |

The API process is a Kafka consumer too. Its lifespan registers two subscriber groups: `sse-bridge-pool` copies 17 execution, pod and result event types into Redis for SSE, and `notification-service` turns `execution_completed`, `execution_failed` and `execution_timeout` into notifications.

## Worker

The worker runs in its own container from the same backend image as the API, with the command `python -m app.worker`. Its entry point is `app/worker.py`, and its one Kafka router is in `app/events/handlers.py`. The parts call each other directly.

| Part | Consumes | Publishes |
|--------|----------|-----------|
| Execution scheduler | `execution_requested`, `execution_cancelled` | nothing itself |
| K8s worker | nothing, the scheduler calls it | `pod_created` |
| Pod monitor | nothing, it watches the Kubernetes API | `pod_scheduled`, `pod_running`, `pod_terminated` |
| Result processor | nothing, the pod monitor and the scheduler call it | `execution_completed`, `execution_failed`, `execution_timeout`, then `result_stored`, or `result_failed` when storing fails |
| DLQ processor | nothing | retried events and `dlq_message_retried` |

The execution scheduler puts each request into the execution queue and has the k8s worker create the pod once a slot is free. A pod that can't be created ends the execution as `failed`. `execution_cancelled` takes the execution out of the queue, stores it as `cancelled`, deletes its pod and frees its slots. An APScheduler job runs `schedule_pending` every 10 seconds next to the consumers.

The k8s worker creates a ConfigMap holding the script and the entrypoint, then the pod, then sets the pod as the ConfigMap's owner so Kubernetes deletes both together. The pod runs as user 1000 with a read-only root filesystem, all capabilities dropped, seccomp `RuntimeDefault`, no service account token, no service links and no host namespaces. The worker refuses to start if `K8S_NAMESPACE` is `default`.

The pod monitor lists and then watches pods labelled `app=integr8s,component=executor`. Each watch window lasts up to 30 seconds, and the worker's watch task opens the next one as soon as the last has ended. It maps pod phases to events, reads the exit code, resource usage and output from the termination message and logs, hands a finished execution to the result processor, deletes the pod and tells the scheduler, so the next execution starts. Deleting the pod frees its share of the ResourceQuota for the next one.

The result processor writes the final status, output and resource usage to MongoDB, records execution metrics and only then publishes the terminal event. If the execution already ended, a cancel for example, it publishes nothing. It doesn't touch Kubernetes.

Replay sessions run in the worker. The admin route stores a scheduled session, and the worker's `EventReplayService` runs it. MongoDB drops finished sessions 48 hours after they complete.

The DLQ processor runs `process_monitoring_cycle` every 10 seconds, which republishes due messages from the `dlq_messages` collection to their original topic for the consumer group that failed on them. The execution scheduler and notification routers save their failed events there. See [Dead Letter Queue](../components/dead-letter-queue.md).

## Idempotent consumers

The execution scheduler's router carries `IdempotencyMiddleware` from `app/events/middlewares.py`, with the `EVENT_BASED` strategy and a 1 hour TTL. It reserves a key in Redis, runs the handler and marks the key completed or failed. A duplicate delivery finds the key and is skipped, so a redelivered `execution_requested` doesn't queue the execution again.

`EVENT_BASED` keys on event type and ID, so it catches a redelivered message. When a caller doesn't pass a strategy, `IdempotencyManager.check_and_reserve` uses `EVENT_BASED`.

## Network isolation

The k8s worker owns the executor network policy and is the only thing that sets it. At startup `ensure_namespace_security` applies a NetworkPolicy named `executor-deny-all` that selects pods labelled `component=executor` and allows no ingress and no egress. The same call labels the namespace with the Pod Security Admission `restricted` profile for enforce, warn and audit. Then `ensure_image_pre_puller_daemonset` applies the `runtime-image-pre-puller` DaemonSet, which pulls every runtime image onto each node. The worker doesn't wait for those pulls, so an execution that arrives first can still hit a cold image pull.

A NetworkPolicy does nothing unless the cluster's network plugin enforces it, so check that before you rely on it. See [Security Policies](../security/policies.md).

For how each process starts and stops, see [Service Lifecycle](lifecycle.md).
