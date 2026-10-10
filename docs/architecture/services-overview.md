# Services overview

This page maps `backend/app/services/` and the workers that run outside the API. Read it for a mental model before you open the code.

## The API's services

Route handlers get these from Dishka. They hold the business logic, talk to MongoDB through repositories and publish events through `UnifiedProducer`.

| Module | What it does |
|--------|--------------|
| `auth_service.py`, `login_lockout.py` | Login, registration, the current user from the JWT cookie, lockout after repeated failed logins. See [Authentication](authentication.md). |
| `execution_service.py` | The facade behind `/execute`. Checks the runtime registry, stores the execution, publishes `ExecutionRequestedEvent`, and publishes `ExecutionCancelledEvent` on cancel or delete. Handles the `Idempotency-Key` header. |
| `execution_queue.py` | `ExecutionQueueService`, the Redis priority queue the saga orchestrator schedules from. See [Execution Queue](execution-queue.md). |
| `saga/` | `SagaOrchestrator`, `ExecutionSaga` and its steps, and `SagaService`, the read side behind the saga routes with ownership checks. |
| `event_service.py`, `kafka_event_service.py` | Reading stored events, and `KafkaEventService.publish_event`, a thin wrapper over `UnifiedProducer` that adds a span and metrics. |
| `event_replay/` | `EventReplayService`, which re-publishes stored events for admins. |
| `sse/` | `SSERedisBus` and `SSEService`. See [SSE](../components/sse/sse-architecture.md). |
| `notification_service.py`, `notification_scheduler.py` | Notifications for finished executions, delivery, subscriptions, and the job that sends scheduled ones. |
| `user_settings_service.py` | Settings stored as events with snapshots and a 5-minute in-process cache. See [User Settings Events](user-settings-events.md). |
| `saved_script_service.py` | CRUD for saved scripts, scoped to the owner. |
| `rate_limit_service.py` | Redis sliding window and token bucket limits per endpoint group. See [Rate Limiting](rate-limiting.md). |
| `idempotency/` | `IdempotencyManager` and its Redis repository. See [Idempotency](idempotency.md). |
| `runtime_settings.py` | `RuntimeSettingsLoader`, which reads the admin-set system settings from MongoDB, falls back to the TOML values and caches the result for 60 seconds. |
| `admin/` | Admin services for users, executions, events and system settings. |
| `k8s_worker/`, `pod_monitor/`, `result_processor/` | The services behind the workers of the same name. |

The API process is a Kafka consumer too. Its lifespan registers two subscriber groups: `sse-bridge-pool` copies 17 execution, pod and result event types into Redis for SSE, and `notification-service` turns `execution_completed`, `execution_failed` and `execution_timeout` into notifications.

## Workers

Each worker runs in its own container from the same backend image as the API, with a different command, for example `python workers/run_k8s_worker.py`. The entry points live in `backend/workers/`. Every subscriber is registered in `app/events/handlers.py`.

| Worker | Consumes | Publishes |
|--------|----------|-----------|
| Saga orchestrator | `execution_requested`, `execution_completed`, `execution_failed`, `execution_timeout`, `execution_cancelled` | `create_pod_command`, `delete_pod_command`, `saga_started`, `saga_cancelled` |
| K8s worker | `create_pod_command`, `delete_pod_command` | `pod_created`, or `execution_failed` when pod creation fails |
| Pod monitor | nothing, it watches the Kubernetes API | `pod_scheduled`, `pod_running`, `pod_terminated`, `execution_completed`, `execution_failed`, `execution_timeout` |
| Result processor | `execution_completed`, `execution_failed`, `execution_timeout` | `result_stored`, or `result_failed` when storing fails |
| Event replay | nothing | nothing, it only cleans up old sessions |
| DLQ processor | nothing | retried events and `dlq_message_retried` |

The saga orchestrator puts each request into the execution queue and runs the saga once a slot is free. The saga steps are `validate_execution`, `allocate_resources` and `create_pod`; the last one publishes the pod command. If a step fails, the compensations of the steps that already ran go in reverse order: `delete_pod` publishes `delete_pod_command` and `release_resources` frees the allocation. Terminal execution events mark the saga done and release the queue slot. `execution_cancelled` takes a queued request out of the queue and marks the saga cancelled, but it doesn't delete a pod that is already running. Two APScheduler jobs run next to the consumers: `check_timeouts` every 30 seconds and `try_schedule_from_queue` every 10 seconds.

The k8s worker creates a ConfigMap holding the script and the entrypoint, then the pod, then sets the pod as the ConfigMap's owner so Kubernetes deletes both together. The pod runs as user 1000 with a read-only root filesystem, all capabilities dropped, seccomp `RuntimeDefault`, no service account token, no service links and no host namespaces. The worker refuses to start if `K8S_NAMESPACE` is `default`.

The pod monitor lists and then watches pods labelled `app=integr8s,component=executor`. Each watch window lasts up to 30 seconds, and an APScheduler job checks every 5 seconds and opens the next one once the last has ended. It maps pod phases to events, reads the exit code, resource usage and output from the termination message and logs, and deletes the pod once it has published a terminal execution event. Deleting the pod frees the Kueue quota for the next one.

The result processor writes the final status, output and resource usage to MongoDB and records execution metrics. It doesn't touch Kubernetes.

The event-replay container only runs `cleanup_old_sessions` every 6 hours. Replay sessions themselves run inside the API process, which owns the `EventReplayService` the admin routes use.

The DLQ processor runs `process_monitoring_cycle` every 10 seconds, which republishes due messages from the `dlq_messages` collection to their original topic. Nothing writes to that collection today, so it has nothing to retry ([#288](https://github.com/HardMax71/Integr8sCode/issues/288)). See [Dead Letter Queue](../components/dead-letter-queue.md).

## Idempotent consumers

Three consumers wrap their handler in `with_idempotency` from `app/events/handlers.py`, which reserves a key in Redis, runs the handler and marks the key completed or failed. A duplicate delivery finds the key and is skipped.

| Consumer | Key strategy | TTL |
|----------|--------------|-----|
| Saga orchestrator, `execution_requested` | `EVENT_BASED` | 1 hour |
| K8s worker, both commands | `CONTENT_HASH` | 1 hour |
| Result processor, all three events | `CONTENT_HASH` | 2 hours |

`EVENT_BASED` keys on event type and ID, so it catches a redelivered message. `CONTENT_HASH` hashes the event without its ID, timestamp and metadata, so it also catches the same command published twice. When a caller doesn't pass a strategy, `IdempotencyManager.check_and_reserve` uses `EVENT_BASED`.

## Network isolation

The k8s worker owns the executor network policy and is the only thing that sets it. At startup `ensure_namespace_security` applies a NetworkPolicy named `executor-deny-all` that selects pods labelled `component=executor` and allows no ingress and no egress. The same call labels the namespace with the Pod Security Admission `restricted` profile for enforce, warn and audit. Then `ensure_image_pre_puller_daemonset` applies the `runtime-image-pre-puller` DaemonSet so every runtime image is already on the node when a pod needs it.

A NetworkPolicy does nothing unless the cluster's network plugin enforces it, so check that before you rely on it. See [Security Policies](../security/policies.md).

For how each process starts and stops, see [Service Lifecycle](lifecycle.md).
