# Architecture overview

This document sketches the system as it actually exists in this repo, using ASCII block diagrams. Each diagram includes labeled arrows (protocols, topics, APIs) and marks public vs private surfaces. Short captions (1–3 sentences) follow each diagram.


## Top-level system (containers/services)

```mermaid
%%{init: {'theme': 'neutral'}}%%
graph TD
    subgraph "Public Internet"
        Browser["Browser SPA"]
    end

    subgraph "Frontend"
        Frontend_service["Nginx + Svelte"]
    end

    subgraph "Backend"
        FastAPI["FastAPI / Uvicorn<br/>(routers, Dishka DI, middlewares)"]
        SSE["SSE Service<br/>(Partitioned router + Redis bus)"]
        Mongo[(MongoDB)]
        Redis[(Redis)]
        Kafka[Kafka]
        Schema["Schema Registry"]
        K8s[Kubernetes API]
        OTel["OTel Collector"]
        VM["VictoriaMetrics"]
        Jaeger["Jaeger"]
    end

    subgraph "Cert Generator"
        CertGen["setup-k8s.sh, TLS"]
    end

    Browser -- "HTTPS 443<br/>SPA + static assets" --> Frontend_service
    Frontend_service -- "HTTPS /api/v1/*<br/>Cookies/CSRF" --> FastAPI
    FastAPI -- "/api/v1/events/*<br/>JSON frames" <--> SSE
    FastAPI -- "Repos CRUD<br/>executions, settings, events" --> Mongo
    FastAPI -- "Rate limiting keys<br/>SSE pub/sub channels" <--> Redis
    FastAPI -- "UnifiedProducer<br/>(events)" --> Kafka
    Kafka -- "UnifiedConsumer<br/>(dispatch)" --> FastAPI
    Kafka --- Schema
    FastAPI -- "pod create/monitor<br/>worker + pod monitor" <--> K8s
    FastAPI -- "metrics/traces (export)" --> OTel
    OTel -- "remote_write (metrics)" --> VM
    FastAPI -- "traces (export)" --> Jaeger
    CertGen -. "cluster setup / certs" .-> K8s
```

Frontend serves the SPA; the SPA calls FastAPI over HTTPS. Backend exposes REST + SSE; Mongo persists state, Redis backs rate limiting and the SSE bus, Kafka carries domain events (with schema registry), and Kubernetes runs/monitors execution pods.


## Backend composition (app/main.py wiring)

```mermaid
%%{init: {'theme': 'neutral'}}%%
mindmap
  root((Backend (FastAPI app)))
    Middlewares
      CorrelationMiddleware (request ID)
      RequestSizeLimitMiddleware
      CacheControlMiddleware
      OTel Metrics (setup_metrics)
    Routers (public)
      /auth (api/routes/auth.py)
      /execute (api/routes/execution.py)
        /result/{id}, /executions/{id}/events
        /user/executions, /example-scripts, /k8s-limits
        /{execution_id}/cancel, /{execution_id}/retry, DELETE /{execution_id}
      /scripts (api/routes/saved_scripts.py)
      /replay (api/routes/replay.py)
      /health (api/routes/health.py)
      /dlq (api/routes/dlq.py)
      /events (api/routes/events.py)
      /events (SSE) (api/routes/sse.py)
        /events/notifications/stream
        /events/executions/{id}
      /notifications (api/routes/notifications.py)
      /saga (api/routes/saga.py)
      /user/settings (api/routes/user_settings.py)
      /admin/users (api/routes/admin/users.py)
      /admin/events (api/routes/admin/events.py)
      /admin/settings (api/routes/admin/settings.py)
      /alerts (api/routes/grafana_alerts.py)
    DI & Providers (Dishka)
      Container (core/container.py, core/providers.py)
      Exception handlers (core/exceptions/handlers.py)
    Services (private)
      ExecutionService (services/execution_service.py)
        Uses ExecutionRepository, UnifiedProducer, EventStore, Settings
      KafkaEventService (services/kafka_event_service.py)
      EventService (services/event_service.py)
      IdempotencyManager (services/idempotency/idempotency_manager.py)
      SSEService (services/sse/sse_service.py)
        SSERedisBus, PartitionedSSERouter, SSEShutdownManager, EventBuffer
      NotificationService (services/notification_service.py)
        UnifiedConsumer handlers (completed/failed/timeout), SSE, throttle
      UserSettingsService (services/user_settings_service.py)
        LRU cache, USER_* events to EventStore/Kafka
      SavedScriptService (services/saved_script_service.py)
      RateLimitService (services/rate_limit_service.py)
      ReplayService (services/event_replay/replay_service.py)
      SagaService (services/saga_service.py)
        SagaOrchestrator, ExecutionSaga, SagaStep (explicit DI)
      K8s Worker (services/k8s_worker/{config,pod_builder,worker}.py)
      Pod Monitor (services/pod_monitor/{monitor,event_mapper}.py)
      Result Processor (services/result_processor/{processor,resource_cleaner}.py)
      Coordinator (services/coordinator/{queue_manager,resource_manager,coordinator}.py)
      EventBusManager (services/event_bus.py)
    Repositories (Mongo, private)
      ExecutionRepository
      EventRepository
      NotificationRepository
      UserRepository
      UserSettingsRepository
      SavedScriptRepository
      SagaRepository
      ReplayRepository
      IdempotencyRepository
      SSERepository
      ResourceAllocationRepository
      Admin repositories (db/repositories/admin/*)
    Events (Kafka plumbing)
      UnifiedProducer, UnifiedConsumer, EventDispatcher (events/core/*)
      EventStore (events/event_store.py)
      SchemaRegistryManager (events/schema/schema_registry.py)
      Topics mapping (infrastructure/kafka/mappings.py)
      Event models (infrastructure/kafka/events/*)
    Mappers (API/domain)
      execution_api_mapper, saved_script_api_mapper, user_settings_api_mapper
      notification_api_mapper, saga_mapper, replay_api_mapper
      admin_mapper, admin_overview_api_mapper, rate_limit_mapper, event_mapper
    Domain
      Enums: execution, events, notification, replay, saga, user, common, kafka
      Models: execution, sse, saga, notification, saved_script, replay, user.settings
      Admin models: overview, settings, user
    External dependencies (private)
      MongoDB (db)
      Redis (rate limit, SSE bus)
      Kafka + Schema Registry
      Kubernetes API (pods)
      OTel Collector + VictoriaMetrics (metrics)
      Jaeger (traces)
    Settings (app/settings.py)
      Runtimes/limits, Kafka/Redis/Mongo endpoints, SSE, rate limiting
```

This outlines backend internals: public routers, DI and services, repositories, event stack, and external dependencies, grounded in the actual modules and paths.


## HTTP request path (representative)

```
Browser (SPA) --HTTPS--> FastAPI Router --DI--> Service --Repo--> MongoDB
                                       \--DI--> Service --Redis--> rate limit (keys)
                                       \--DI--> KafkaEventService --Kafka--> topic
                                       \--SSE-> SSEService --Redis pub/sub--> broadcast
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

    Client->>ApiExec: POST /execute {script, lang, version}
    ApiExec->>Auth: get_current_user()
    Auth-->>ApiExec: UserResponse
    ApiExec->>Idem: check_and_reserve(http:{user}:{key})
    Idem-->>ApiExec: IdempotencyResult
    ApiExec->>ExecSvc: execute_script(script, lang, v, user, ip, UA)
    ExecSvc->>ExecRepo: create execution (queued)
    ExecRepo-->>ExecSvc: created(id)
    ExecSvc->>EStore: persist ExecutionRequested
    ExecSvc->>Kafka: publish execution.requested
    Kafka->>K8sWorker: consume execution.requested
    K8sWorker->>K8sAPI: create pod, run script
    K8sWorker-->>K8sAPI: stream logs/status
    K8sAPI->>PodMon: pod events/logs
    PodMon->>EStore: persist Execution{Completed|Failed|Timeout}
    PodMon->>Kafka: publish execution.{completed|failed|timeout}
    Kafka->>ResProc: consume execution result
    ResProc->>ExecRepo: update result (status/output/errors/usage)
    ResProc->>RedisBus: publish result_stored(execution_id)
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
graph TD
    subgraph " "
        style " " fill:none,stroke:none
        SSEService["SSEService<br/>(per-request Gen)"]
        subgraph "Redis Pub/Sub (private)"
            RedisBus["SSERedisBus"]
        end
    end

    Router["PartitionedSSERouter<br/>(N partitions)<br/>(manages consumers/subs)"]

    subgraph "FastAPI routes (public)" as ApiRoutes
        direction LR
        RouteExec["/events/executions/{id}"]
        RouteNotify["/events/notifications/stream"]
    end

    %% ---- Connections ----

    %% Control/Request Flow
    ApiRoutes -- "Request" --> Router
    Router --> SSEService
    SSEService <--> |"sub/pub"| RedisBus

    %% Data Stream Flow
    RedisBus -.-> |"stream JSON frames"| ApiRoutes
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

    subgraph "NotificationService (private)"
        NotificationSvc["
            <b>NotificationService</b><br/>
            - UnifiedConsumer (typed handlers for completed/failed/timeout)<br/>
            - Repository: notifications + subscriptions (Mongo)<br/>
            - Channels:<br/>
              &nbsp;&nbsp;- IN_APP: persist + publish SSE bus (Redis)<br/>
              &nbsp;&nbsp;- WEBHOOK: httpx POST<br/>
              &nbsp;&nbsp;- SLACK: httpx POST to slack_webhook<br/>
            - Throttle cache (in-memory) per user/type
        "]
    end

    ApiNotifications["/api/v1/notifications (public)<br/>(list, mark read, mark all read, subscriptions, unread-count)"]
    ApiSSE["/events/notifications/stream (SSE, public)"]

    Kafka --> NotificationSvc
    NotificationSvc --> ApiNotifications
    NotificationSvc --> ApiSSE
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


## Saved scripts & user settings (event-sourced settings)

```
 /api/v1/scripts/*  -> SavedScriptService -> SavedScriptRepository (Mongo)

 /api/v1/user/settings/* -> UserSettingsService
        |-- UserSettingsRepository (snapshot + events in Mongo)
        |-- KafkaEventService (USER_* events) to EventStore/Kafka
        |-- Cache (LRU) in process
```

Saved scripts are simple CRUD per user. User settings are reconstructed from snapshots plus events, with periodic snapshotting.


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
