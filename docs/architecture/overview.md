# Architecture overview

Integr8sCode runs user scripts in Python, Node.js, Ruby, Bash or Go, each in its own short-lived Kubernetes pod. A Svelte SPA submits the script to a FastAPI backend. The backend stores the execution, publishes an event to Kafka and returns right away. Workers pick the event up, run the pod and store the result, and the browser follows progress over SSE.

<div class="grid cards" markdown>

-   :material-layers-outline:{ .lg .middle } **[Middleware](middleware.md)**

    The seven layers every request passes through before it reaches a route

-   :material-cog-outline:{ .lg .middle } **[Services](services-overview.md)**

    What lives in `backend/app/services/` and what each part of the worker consumes and publishes

-   :material-transit-connection-variant:{ .lg .middle } **[Kafka Topics](kafka-topic-architecture.md)**

    One topic per event type, consumer groups, replay and the DLQ

-   :material-broadcast:{ .lg .middle } **[SSE](../components/sse/sse-architecture.md)**

    How Kafka events reach the browser through Redis pub/sub

-   :material-robot-industrial-outline:{ .lg .middle } **[Worker](../components/workers/index.md)**

    The one background process that runs next to the API

</div>

## System overview

![System diagram](/assets/images/system_diagram.svg)

The browser loads the SPA from the frontend container, an nginx that serves HTTPS on port 5001 and proxies `/api` to the backend over HTTPS, checking the backend's own certificate. The backend runs FastAPI under Gunicorn with Uvicorn workers and serves both REST and SSE. Kafka runs in KRaft mode and creates topics on first use, so there is no topic setup step. Events travel as JSON that FastStream serializes from the Pydantic models.

The worker is one more container from the same backend image, running `python -m app.worker`. Inside it, the execution scheduler starts executions from a Redis-backed queue, the k8s worker creates their pods through the Kubernetes API, the pod monitor watches the pods, and the result processor writes results to MongoDB. A DLQ job retries failed events every 10 seconds.

The observability profile adds an OpenTelemetry Collector that ships traces to Jaeger, metrics to VictoriaMetrics and logs to Loki, with Grafana on top of all three. Kafdrop is under the debug profile. No container runs once and exits. nginx and the backend each make their own TLS certificate when they first start, and the backend seeds the users before it serves. The worker reads k3s's own kubeconfig and creates the `integr8scode` namespace with its NetworkPolicy and ResourceQuota.

## Backend wiring

```mermaid
graph TD
    subgraph "Backend (FastAPI app)"
        App["FastAPI / Uvicorn"]
        Middlewares["Middlewares"]
        RoutesDI["Routes + DI"]
        Services["Services"]
        Repos["Repositories"]
        Events["Kafka Layer"]
    end

    Mongo[(MongoDB)]
    Redis[(Redis)]
    Kafka[Kafka]
    Observability["Observability"]

    App --> Middlewares --> RoutesDI --> Services
    Services --> Repos --> Mongo
    Services --> Events <-->|"produce / consume"| Kafka
    Services <-->|"keys + SSE bus"| Redis
    App -.->|"OTLP"| Observability

    click Middlewares "../middleware/" "Request processing pipeline"
    click Services "../services-overview/" "Business logic services"
    click Events "../kafka-topic-architecture/" "Kafka event system"
    click Observability "../../operations/tracing/" "Distributed tracing with OpenTelemetry"
```

??? note "Legend"
    - Middlewares, outermost first: CORS, CacheControl, SecurityHeaders, RequestSizeLimit, CSRF, RateLimit, Metrics
    - Routes + DI: REST and SSE endpoints, with services injected by Dishka
    - Services: auth, execution, events, SSE, idempotency, notifications, user settings, rate limits, saved scripts, replay, admin
    - Kafka layer: `UnifiedProducer` on the way out, FastStream subscribers on the way in
    - Observability: the OTel Collector, which forwards to VictoriaMetrics, Jaeger and Loki

A request passes through seven middlewares before it reaches a route handler. Handlers get their services from Dishka, services read and write MongoDB through repositories, and the event-driven flows (executions, auth, user settings, notifications) publish events through `UnifiedProducer`, which stores the event in MongoDB first and then sends it to Kafka. Saved scripts and admin changes to users and system settings write to MongoDB without an event. Redis holds rate limit counters, idempotency keys, the execution queue and the SSE pub/sub channels.

The API process also consumes Kafka. On startup it registers two subscriber groups: `sse-bridge-pool`, which copies execution events into Redis for SSE, and `notification-service`, which turns finished executions into notifications.

## Execution lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant API
    participant Kafka
    participant Sched as Execution Scheduler
    participant K8s as K8s Worker
    participant Monitor as Pod Monitor
    participant Result as Result Processor

    Client->>API: POST /api/v1/execute
    API->>Kafka: execution_requested
    API-->>Client: 200 {execution_id, status}
    Client->>API: GET /api/v1/events/executions/{id} (SSE)
    Kafka->>Sched: execution_requested
    Sched->>K8s: create_pod
    K8s->>Kafka: pod_created
    Monitor->>Kafka: pod_scheduled, pod_running
    Monitor->>Result: execution_completed
    Result->>Kafka: execution_completed, result_stored
    Monitor->>Sched: finish
    Kafka->>API: events for this execution (sse-bridge-pool)
    API-->>Client: SSE frames, closes after result_stored

    link Sched: Docs @ ../../components/workers/execution_scheduler/
    link K8s: Docs @ ../../components/workers/k8s_worker/
    link Monitor: Docs @ ../../components/workers/pod_monitor/
    link Result: Docs @ ../../components/workers/result_processor/
```

The rate limit middleware has already run by the time the route sees the request. If the client sent an `Idempotency-Key` header it used before, the [idempotency](idempotency.md) layer returns the earlier execution instead of creating a new one, or 409 while that first request is still in flight. Otherwise the execution service checks the language and version against the [runtime registry](runtime-registry.md) and rejects an unknown pair with 422. Then it stores the execution in MongoDB, publishes `execution_requested` and answers with the execution ID and its status.

The execution scheduler in the worker puts the request into the [execution queue](execution-queue.md) and, once a slot is free, has the k8s worker create a ConfigMap with the script and a hardened pod. The k8s worker publishes `pod_created`; if the Kubernetes API refused, the execution is stored as `failed` instead. The pod monitor watches the pod and publishes `pod_scheduled` and `pod_running`. When the pod ends, the monitor reads its output and hands `execution_completed`, `execution_failed` or `execution_timeout` to the result processor. Then it deletes the pod, which frees its share of the ResourceQuota, and Kubernetes garbage-collects the ConfigMap through its owner reference.

The result processor writes the final state and output to MongoDB, then publishes the terminal event and `result_stored`, or `result_failed` if the write failed. Last, the monitor tells the scheduler the execution finished, so its queue slot frees and the next execution starts. A cancel goes the same way in reverse: the scheduler takes `execution_cancelled`, stores the execution as `cancelled` and deletes its pod.

## SSE

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant Router as SSE route
    participant SSE as SSEService
    participant Bus as Redis pub/sub
    participant Bridge as sse-bridge-pool

    Client->>Router: GET /api/v1/events/executions/{id}
    Router->>SSE: create_execution_stream (404 or 403 if not allowed)
    SSE-->>Client: current status from MongoDB
    SSE->>Bus: SUBSCRIBE sse:exec:{id}

    loop until a terminal event
        Bridge->>Bus: PUBLISH sse:exec:{id}
        Bus-->>SSE: message
        SSE-->>Client: SSE frame
    end

    link SSE: Docs @ ../../components/sse/sse-architecture/
```

SSE goes through Redis so that any API process can serve any client. All API processes share the `sse-bridge-pool` consumer group, so Kafka hands each event to exactly one of them. That process publishes the event to the Redis channel `sse:exec:{execution_id}`, and Redis delivers it to whichever process holds the client's connection. The bridge forwards 17 event types: the execution, pod and result events.

The stream opens with the execution's current status read from MongoDB, since events published before the subscription aren't replayed. When `result_stored` arrives, the service loads the stored result and attaches it to that frame. The stream ends after `result_stored`, `result_failed`, `execution_failed` or `execution_timeout`, or when the client disconnects. Leaving the generator closes the Redis subscription.

Notifications use the same bus on `sse:notif:{user_id}` through `GET /api/v1/events/notifications/stream`. That stream stays open until the client goes away and sends a ping every 30 seconds.

## Kafka and replay

Kafka carries all asynchronous work, with [one topic per event type](kafka-topic-architecture.md). The [replay system](../components/event-replay.md) lets admins re-publish stored events; the worker sends them. A failed handler's event goes to the [dead letter queue](../components/dead-letter-queue.md) and is retried for the consumer group that failed.

## Notifications

```mermaid
graph TD
    Kafka["Kafka"] -->|"execution_completed / failed / timeout"| NotificationSvc["NotificationService (API)"]
    NotificationSvc -->|"store"| Mongo[(MongoDB)]
    NotificationSvc -->|"publish sse:notif:{user_id}"| Redis["Redis"]
    Redis --> Stream["/api/v1/events/notifications/stream"]

    click NotificationSvc "../../operations/notification-types/" "Notification types"
```

`NotificationService` runs inside the API under the `notification-service` consumer group. For each completed, failed or timed-out execution it stores a notification in MongoDB and pushes it to the user's SSE channel. Notifications are in-app only.

## API surface

The public surface is the REST and SSE endpoints under `/api/v1/`. MongoDB, Redis, Kafka, the Kubernetes API and the worker stay internal. The frontend talks to the backend with fetch and EventSource and [cookie-based auth](authentication.md). The [admin routes](../operations/admin-api.md) under `/api/v1/admin/` require the admin role. The OpenAPI schema and the Swagger UI are served only when `DEVELOPMENT_MODE` is on. See the [API Reference](../reference/api-reference.md) for the full list.
