# Middleware

The backend uses a stack of ASGI middleware to handle cross-cutting concerns like rate limiting, request size
validation, caching, and metrics collection. Middleware runs in order from outermost to innermost, with response
processing in reverse order.

## Middleware Stack

The middleware is applied in this order (outermost first):

1. **RequestSizeLimitMiddleware** - Rejects oversized requests
2. **RateLimitMiddleware** - Enforces per-user/per-endpoint limits
3. **CacheControlMiddleware** - Adds cache headers to responses
4. **MetricsMiddleware** - Collects HTTP request metrics

## Request Size Limit

Rejects requests exceeding a configurable size limit (default 10MB). This protects against denial-of-service attacks
from large payloads.

```python
--8<-- "backend/app/core/middlewares/request_size_limit.py:5:10"
```

Requests exceeding the limit receive a 413 response:

```json
{"detail": "Request too large. Maximum size is 10.0MB"}
```

The middleware checks the `Content-Length` header before reading the body, avoiding wasted processing on oversized
requests.

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
| [`core/middlewares/__init__.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/middlewares/__init__.py)                     | Middleware exports      |
| [`core/middlewares/rate_limit.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/middlewares/rate_limit.py)                 | Rate limiting           |
| [`core/middlewares/cache.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/middlewares/cache.py)                           | Cache headers           |
| [`core/middlewares/request_size_limit.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/middlewares/request_size_limit.py) | Request size validation |
| [`core/middlewares/metrics.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/middlewares/metrics.py)                       | HTTP and system metrics |
