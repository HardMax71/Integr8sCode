# Architecture overview

In this file, you can find broad description of main components of project architecture. 
Preciser info about peculiarities of separate components (SSE, Kafka topics, DLQ, ..) are in 
[docs](./../backend/docs).

## Top-level system (containers/services)

<img src="./system_diagram.png" alt="System diagram">

The SPA hits the frontend, which proxies to the API over HTTPS; the API
serves both REST and SSE. Kafka carries events with Schema Registry and Zookeeper backing it; kafka-
init seeds topics. All workers are separate containers subscribed to Kafka; the k8s-worker talks to the
Kubernetes API to run code, the pod-monitor watches pods, the result-processor writes results to Mongo
and nudges Redis for SSE fanout, and the saga-orchestrator coordinates long flows with Mongo and Redis.
Traces and metrics from every service go to the OpenTelemetry Collector, which exports traces to Jaeger
and metrics to VictoriaMetrics; Grafana reads from VictoriaMetrics, and Kafdrop gives you a quick Kafka
UI. The cert generator and shared CA provide TLS for frontend and backend and help bootstrap kube access.


## Backend composition (app/main.py wiring)

```mermaid
  %%{init: {'theme': 'neutral'}}%%
  graph LR
      subgraph "Backend (FastAPI app)"
          direction LR
          App["FastAPI / Uvicorn"]
          Middlewares["Middlewares"]
          Routers["Routers (REST + SSE)"]
          DI["DI & Providers (Dishka)"]
          Services["Core Services (Execution, Events, SSE, Idempotency, Notifications, User Settings, Rate
  Limit, Saved Scripts, Replay, Saga API)"]
          Events["Kafka plumbing (Producer, Consumer, Dispatcher, EventStore, SchemaRegistryManager)"]
          Repos["Repositories"]
      end

          Mongo[(MongoDB)]
          Redis[(Redis)]
          Kafka[Kafka]
          Schema["Schema Registry"]
          K8s["Kubernetes API"]
          OTel["OTel Collector"]
          VM["VictoriaMetrics"]
          Jaeger["Jaeger"]


      %% App internals
      App --> Middlewares
      App --> Routers
      App --> DI
      App --> Services
      Services --> Repos
      Services --> Events

      %% Infra edges (high level only)
      Repos --> Mongo
      Services <-->|"keys + SSE bus"| Redis
      Events <-->|"produce/consume"| Kafka
      Events ---|"subjects/IDs"| Schema
      Services -->|"read limits"| K8s

      %% Telemetry edges
      App -->|"OTLP traces + metrics"| OTel
      OTel -->|"remote_write (metrics)"| VM
      OTel -->|"OTLP gRPC (traces)"| Jaeger
```

FastAPI under Uvicorn exposes REST and SSE routes, with middleware and DI wiring the core services.
Those services use Mongo-backed repositories for state and a unified Kafka layer to publish and react
to events, with the schema registry ensuring compatibility. Redis handles rate limiting and SSE fanout. 
Telemetry flows through the OpenTelemetry Collector—metrics to VictoriaMetrics for Grafana and traces
to Jaeger. Kubernetes interactions are read via the API. This view focuses on the app’s building blocks;
event workers live in the system diagram.

## HTTP request path (representative)

```mermaid
%%{init: {'theme': 'neutral'}}%%
  graph TD
    Browser["Browser (SPA)"] -->|"HTTPS"| Router["FastAPI Router"]

    Router -->|"DI"| Svc1["Service"]
    Svc1 -->|"Repo"| MongoDB[(MongoDB)]

    Router -->|"DI"| Svc2["Service"]
    Svc2 -->|"rate limit (keys)"| Redis[(Redis)]

    Router -->|"DI"| KafkaSvc["KafkaEventService"]
    KafkaSvc -->|"Kafka"| Kafka[(Kafka)]
    Kafka -->|"topic"| Topic["topic"]

    Router -->|"SSE"| SSESvc["SSEService"]
    SSESvc -->|"Redis pub/sub"| Broadcast["broadcast"]
```

Routers resolve dependencies via Dishka and call services. Services talk to Mongo, Redis, Kafka based on the route; SSE streams push via Redis bus to all workers.


## Execution lifecycle (request -> result -> SSE)

```mermaid
%%{init: {'theme': 'neutral'}}%%
sequenceDiagram
    autonumber
    actor Client
    participant ApiExec as API (Exec Route)<br/>/api/v1/execute
    participant Auth as AuthService
    participant Idem as IdempotencyManager
    participant ExecSvc as ExecutionService
    participant ExecRepo as ExecutionRepository<br/>(Mongo)
    participant EStore as EventStore<br/>(Mongo)
    participant Kafka as Kafka
    participant K8sWorker as K8s Worker
    participant K8sAPI as Kubernetes API
    participant PodMon as Pod Monitor
    participant ResProc as Result Processor
    participant RedisBus as SSERedisBus<br/>(Redis pub/sub)
    participant ApiSSE as API (SSE Route)<br/>/events/executions/{id}
    participant SSE as SSEService

    Client->>ApiExec: POST /execute<br>{script, lang, version}
    ApiExec->>Auth: get_current_user()
    Auth-->>ApiExec: UserResponse
    ApiExec->>Idem: check_and_reserve(http:{user}:{key})
    Idem-->>ApiExec: IdempotencyResult
    ApiExec->>ExecSvc: execute_script(script, lang, v, user, ip, UA)
    ExecSvc->>ExecRepo: create execution<br>(queued)
    ExecRepo-->>ExecSvc: created(id)
    ExecSvc->>EStore: persist<br>ExecutionRequested
    ExecSvc->>Kafka: publish<br>execution.requested
    Kafka->>K8sWorker: consume<br>execution.requested
    K8sWorker->>K8sAPI: create pod,<br>run script
    K8sWorker-->>K8sAPI: stream<br>logs/status
    K8sAPI->>PodMon: pod events/logs
    PodMon->>EStore: persist Execution{Completed|Failed|Timeout}
    PodMon->>Kafka: publish execution.{completed|failed|timeout}
    Kafka->>ResProc: consume execution result
    ResProc->>ExecRepo: update result<br>(status/output/errors/usage)
    ResProc->>RedisBus: publish<br>result_stored(execution_id)
    ApiExec-->>Client: 200 {execution_id}

    rect rgb(230, 230, 230)
        note over Client, ApiSSE: Client subscribes to updates
        Client->>ApiSSE: GET /events/executions/{id}
        ApiSSE->>Auth: get_current_user()
        Auth-->>ApiSSE: UserResponse
        ApiSSE->>SSE: create_execution_stream(execution_id, user)
        SSE->>RedisBus: subscribe channel:{execution_id}
        RedisBus-->>SSE: events..., result_stored
        SSE-->>Client: JSON event frames (until result_stored)
    end
```

Execution is event-driven end-to-end. The request records an execution and emits events; workers and the pod monitor complete it; the result is persisted and the SSE stream closes on result_stored.


## SSE architecture (execution and notifications)

```mermaid
 %%{init: {'theme': 'neutral'}}%%
  sequenceDiagram
      autonumber
      actor Client
      participant Api as FastAPI Route
      participant Router as PartitionedSSERouter
      participant SSE as SSEService (per-request)
      participant Bus as SSERedisBus (Redis Pub/Sub)

      Client->>Api: GET /events/...<br>(Accept: text/event-stream)
      Api->>Router: handle(request)
      Router->>SSE: create stream<br>(execution_id / user)
      SSE->>Bus: SUBSCRIBE channel:{...}
      Api-->>Client: 200 OK + SSE headers (stream open)

      loop until closed
          Bus-->>SSE: message (JSON)
          SSE-->>Client: SSE frame (data: {...})
      end

      alt terminal event / timeout / shutdown
          SSE->>Bus: UNSUBSCRIBE
          SSE-->>Client: event: end/close
      else client disconnect
          SSE->>Bus: UNSUBSCRIBE
      end
```

All app workers publish/consume via Redis so SSE works across processes; streams end on result_stored (executions) and on client close or shutdown (notifications).


## Saga orchestration (execution_saga)

```mermaid
%%{init: {'theme': 'neutral'}}%%
graph TD
    SagaService[SagaService]
    Orchestrator[SagaOrchestrator]
    ExecutionSaga["ExecutionSaga<br/>(steps/compensations)"]
    SagaRepo[(SagaRepository<br/>Mongo)]
    EventStore[(EventStore + Kafka topics)]

    SagaService -- starts --> Orchestrator
    SagaService --> SagaRepo

    Orchestrator -- "binds explicit dependencies<br/>(producers, repos, command publisher)" --> ExecutionSaga
    Orchestrator --> EventStore

    ExecutionSaga -- "step.run(...) -> publish commands (Kafka)" --> EventStore
    ExecutionSaga -- "compensation() -> publish compensations" --> EventStore
```

Sagas use explicit DI (no context-based injection). Only serializable public data is persisted; runtime objects are not stored.


## Notifications (in-app, webhook, Slack, SSE)

```mermaid
%%{init: {'theme': 'neutral'}}%%
  graph TD
      Kafka["[Execution events]<br/>(Kafka topics)"]

      NotificationSvc["NotificationService"]

      subgraph "SSE (delivery path)"
          SSESvc["SSEService"]
          RedisBus["SSERedisBus (Redis Pub/Sub)"]
      end

      ApiNotifications["/api/v1/notifications (REST)"]
      ApiSSE["/events/notifications/stream (SSE)"]

      %% Event ingress
      Kafka -- "(1) execution result events (completed/failed/timeout)" --> NotificationSvc

      %% In‑app channel delivery
      NotificationSvc -- "(2) publish in-app notification" --> RedisBus
      SSESvc -- "(3) subscribe by user_id" --> RedisBus
      RedisBus -. "(4) JSON events to SSEService" .-> SSESvc
      SSESvc -- "(5) SSE frames to client" --> ApiSSE

      %% REST control plane
      ApiNotifications -- "(6) fetch / mark-read / manage-subscriptions" --> NotificationSvc

      %% Other channels
      Webhook["3rd party webhook endpoint"]:::ext
      Slack["Slack incoming webhook"]:::ext
      NotificationSvc -- "(2) HTTP POST (webhook)" --> Webhook
      NotificationSvc -- "(2) HTTP POST (Slack)" --> Slack

      classDef ext fill:#f6f6f6,stroke:#aaa,color:#333;
```

NotificationService processes execution events; in-app notifications are stored and streamed to users; webhooks/Slack are sent via httpx.


## Rate limiting (dependency + Redis)

```
 [Any router] --Depends(check_rate_limit)--> check_rate_limit (DI)
        |                                    |
        |                                    |-- resolve user (optional) -> identifier (user_id or ip:...)
        |                                    |-- RateLimitService.check_rate_limit(...)
        |                                    |      Redis keys: rate_limit:*  (window/token-bucket)
        |                                    |-- set X-RateLimit-* headers on request.state
        |                                    |-- raise 429 with headers when denied
        v                                    v
   handler continues or fails           Redis (private)
```

Anonymous users are limited by IP with a 0.5 multiplier; authenticated users by user_id. Admin UI surfaces per-user config and usage.


## Replay (events)

```
  /api/v1/replay/sessions (admin) --> ReplayService
         |                               |
         |                               |-- ReplayRepository (Mongo) for sessions
         |                               |-- EventStore queries filters/time ranges
         |                               |-- UnifiedProducer to Kafka (target topic)
         v                               v
    JSON summaries                    Kafka topics (private)
```

Replay builds a session from filters and re-emits historical events to Kafka; API exposes session lifecycle and progress.


## DLQ and admin tooling

```
  Kafka DLQ topic <-> DLQ manager (retry/backoff, thresholds)
  /api/v1/admin/events/* -> admin repos (Mongo) for events query/delete
  /api/v1/admin/users/* -> users repo (Mongo) + rate limit config
  /api/v1/admin/settings/* -> system settings (Mongo)
```

Dead letter queue management, events/query cleanup, and admin user/rate-limit endpoints are exposed under /api/v1/admin/* for admins.


## Frontend to backend paths (selected)

```
Svelte routes/components -> API calls:
  - POST /api/v1/auth/register|login|logout
  - POST /api/v1/execute, GET /api/v1/result/{id}
  - GET /api/v1/events/executions/{id}  (SSE)
  - GET /api/v1/notifications, PUT /api/v1/notifications/{id}/read
  - GET /api/v1/events/notifications/stream (SSE)
  - GET/PUT /api/v1/user/settings/*
  - GET/PUT /api/v1/notifications/subscriptions/*
  - GET/POST /api/v1/replay/* (admin)
  - GET/PUT /api/v1/admin/users/* (admin rate limits)
```

SPA uses fetch and EventSource to the backend; authentication is cookie-based and used on SSE via withCredentials.


## Topics and schemas (Kafka)

```
infrastructure/kafka/events/* : Pydantic event models
infrastructure/kafka/mappings.py: event -> topic mapping
events/schema/schema_registry.py: schema manager
events/core/{producer,consumer,dispatcher}.py: unified Kafka plumbing
```

Typed events for executions, notifications, saga, system, user, and pod are produced and consumed via UnifiedProducer/Consumer; topics are mapped centrally.


## Public vs private surfaces (legend)

```
Public to users:
  - HTTPS REST: /api/v1/* (all routers listed above)
  - HTTPS SSE:  /api/v1/events/*

Private/internal only:
  - MongoDB (all repositories)
  - Redis (rate limiting keys, SSE bus channels)
  - Kafka & schema registry (events)
  - Kubernetes API (pod build/run/monitor)
  - Background tasks (consumers, monitors, result processor)
```

Only REST and SSE endpoints are part of the public surface; everything else is behind the backend.
