# Middleware & App-Level Guards

The backend uses ASGI middleware for cross-cutting concerns like rate limiting, caching, and metrics collection, plus a
FastAPI app-level dependency for request size enforcement. Middleware runs in order from outermost to innermost, with
response processing in reverse order.

## Middleware Stack

The middleware is applied in this order (outermost first):

1. **RateLimitMiddleware** - Enforces per-user/per-endpoint limits
2. **CacheControlMiddleware** - Adds cache headers to responses
3. **MetricsMiddleware** - Collects HTTP request metrics

## Request Size Limit (App Dependency)

Request size enforcement is implemented as a FastAPI app-level dependency (`check_request_size` in
`app/api/dependencies.py`) rather than ASGI middleware. It is registered in `FastAPI(dependencies=[...])` so it runs on
every request.

The dependency uses a two-phase approach to reject oversized requests without buffering the entire payload into memory:

1. **Content-Length fast-path** — if the header is present and exceeds `MAX_REQUEST_SIZE_MB`, the request is rejected
   immediately with zero body I/O.
2. **Streaming read with cap** — the body is read chunk-by-chunk via `request.stream()`. As soon as accumulated bytes
   exceed the limit, a 413 is raised. Only ~one chunk past the limit ever enters memory, not the full payload. On
   success the body is cached on `request._body` so downstream `request.body()` calls work without re-reading the
   stream.

The limit is configured via `MAX_REQUEST_SIZE_MB` in `config.toml` (default 10).

Requests exceeding the limit receive a 413 response:

```json
{"detail": "Request too large. Maximum size is 10MB"}
```

!!! note "Why not middleware?"
    A previous implementation used `RequestSizeLimitMiddleware` that only checked the `Content-Length` header. This was
    trivially bypassable by omitting the header or lying about the value. A pure ASGI middleware that wraps `receive()`
    is possible but requires closures for per-request state. The FastAPI dependency approach is simpler, testable, and
    has access to `request.app.state.settings` for configuration.

## Rate Limit

The `RateLimitMiddleware` intercepts all HTTP requests and checks them against configured rate limits.
See [Rate Limiting](rate-limiting.md) for the full algorithm details.

Excluded paths bypass rate limiting:

```python
--8<-- "backend/app/core/middlewares/rate_limit.py:26:38"
```

When a request is allowed, rate limit headers are added to the response. When rejected, a 429 response is returned with
`Retry-After` indicating when to retry.

## Cache Control

Adds appropriate `Cache-Control` headers to GET responses based on endpoint patterns:

```python
--8<-- "backend/app/core/middlewares/cache.py:7:16"
```

| Endpoint                    | Policy            | TTL        |
|-----------------------------|-------------------|------------|
| `/api/v1/k8s-limits`        | public            | 5 minutes  |
| `/api/v1/example-scripts`   | public            | 10 minutes |
| `/api/v1/auth/verify-token` | private, no-cache | -          |
| `/api/v1/notifications`     | private, no-cache | -          |

Public endpoints also get a `Vary: Accept-Encoding` header for proper proxy caching. Cache headers are only added to
successful (200) responses.

## Metrics

The `MetricsMiddleware` collects HTTP request telemetry using OpenTelemetry:

```python
--8<-- "backend/app/core/middlewares/metrics.py:27:45"
```

The middleware tracks:

- **Request count** by method, path template, and status code
- **Request duration** histogram
- **Request/response size** histograms
- **Active requests** gauge

Path templates use pattern replacement to reduce metric cardinality:

```python
--8<-- "backend/app/core/middlewares/metrics.py:104:118"
```

UUIDs, numeric IDs, and MongoDB ObjectIds are replaced with `{id}` to prevent metric explosion.

## System Metrics

In addition to HTTP metrics, the middleware module provides system-level observables:

```python
--8<-- "backend/app/core/middlewares/metrics.py:169:188"
```

These expose:

- `system_memory_bytes` - System memory (used, available, percent)
- `system_cpu_percent` - System CPU utilization
- `process_metrics` - Process RSS, VMS, CPU, thread count

## Key Files

| File                                                                                                                                               | Purpose                 |
|----------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------|
| [`core/middlewares/__init__.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/middlewares/__init__.py)                     | Middleware exports       |
| [`core/middlewares/rate_limit.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/middlewares/rate_limit.py)                 | Rate limiting            |
| [`core/middlewares/cache.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/middlewares/cache.py)                           | Cache headers            |
| [`core/middlewares/metrics.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/middlewares/metrics.py)                       | HTTP and system metrics  |
| [`api/dependencies.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/api/dependencies.py)                                      | Request size enforcement |
