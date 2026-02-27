# Middleware

The backend uses a stack of ASGI middleware to handle cross-cutting concerns like rate limiting, request size
validation, caching, and metrics collection. Middleware runs in order from outermost to innermost, with response
processing in reverse order.

## Middleware Stack

The middleware is applied in this order (outermost first):

1. **MetricsMiddleware** - Collects HTTP request metrics
2. **RateLimitMiddleware** - Enforces per-user/per-endpoint limits
3. **CSRFMiddleware** - Validates CSRF tokens on state-changing requests
4. **RequestSizeLimitMiddleware** - Rejects oversized requests
5. **CacheControlMiddleware** - Adds cache headers to responses
6. **CORSMiddleware** - Handles Cross-Origin Resource Sharing headers

## Request Size Limit

Rejects requests exceeding a configurable size limit (default 10MB). This protects against denial-of-service attacks
from large payloads.

```python
--8<-- "backend/app/core/middlewares/request_size_limit.py:RequestSizeLimitMiddleware"
```

Requests exceeding the limit receive a 413 response:

```json
{"detail": "Request too large. Maximum size is 10.0MB"}
```

The middleware checks the `Content-Length` header before reading the body, avoiding wasted processing on oversized
requests.

## Rate Limit

The `RateLimitMiddleware` intercepts all HTTP requests and checks them against configured [rate limits](rate-limiting.md).

Excluded paths bypass rate limiting:

```python
--8<-- "backend/app/core/middlewares/rate_limit.py:excluded_paths"
```

When a request is allowed, rate limit headers are added to the response. When rejected, a 429 response is returned with
`Retry-After` indicating when to retry.

## Cache Control

Adds appropriate `Cache-Control` headers to GET responses based on endpoint patterns:

```python
--8<-- "backend/app/core/middlewares/cache.py:cache_policies"
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
--8<-- "backend/app/core/middlewares/metrics.py:instruments"
```

The middleware tracks:

- **Request count** by method, path template, and status code
- **Request duration** histogram
- **Request/response size** histograms
- **Active requests** gauge

Path templates use pattern replacement to reduce metric cardinality:

```python
--8<-- "backend/app/core/middlewares/metrics.py:path_template"
```

UUIDs, numeric IDs, and MongoDB ObjectIds are replaced with `{id}` to prevent metric explosion.

## CSRF Protection

The `CSRFMiddleware` validates a CSRF token on all state-changing requests (POST, PUT, DELETE). The token is issued at login and must be sent in the `X-CSRF-Token` header. GET and other safe methods are exempt.

## System Metrics

In addition to HTTP metrics, the middleware module provides system-level observables:

```python
--8<-- "backend/app/core/middlewares/metrics.py:system_metrics"
```

These expose:

- `system_memory_bytes` - System memory (used, available, percent)
- `system_cpu_percent` - System CPU utilization
- `process_metrics` - Process RSS, VMS, CPU, thread count

## Key Files

<div class="grid cards" markdown>

-   :material-speedometer:{ .lg .middle } **[rate_limit.py](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/middlewares/rate_limit.py)**

    Per-user / per-endpoint rate limiting

-   :material-cached:{ .lg .middle } **[cache.py](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/middlewares/cache.py)**

    Cache-Control headers for GET responses

-   :material-file-document-check-outline:{ .lg .middle } **[request_size_limit.py](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/middlewares/request_size_limit.py)**

    Reject oversized payloads before reading the body

-   :material-chart-line:{ .lg .middle } **[metrics.py](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/middlewares/metrics.py)**

    HTTP request telemetry and system-level observables

-   :material-shield-lock:{ .lg .middle } **[csrf.py](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/core/middlewares/csrf.py)**

    CSRF token validation for state-changing requests

</div>
