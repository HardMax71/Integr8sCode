# Middleware

`create_app` in `app/main.py` adds seven ASGI middlewares. Starlette's `add_middleware` puts each new one outside the previous ones, so the last one added runs first. A request passes through them in this order, and the response comes back in reverse:

1. `CORSMiddleware`
2. `CacheControlMiddleware`
3. `SecurityHeadersMiddleware`
4. `RequestSizeLimitMiddleware`
5. `CSRFMiddleware`
6. `RateLimitMiddleware`
7. `MetricsMiddleware`

The order has visible effects. A request that fails the size limit, CSRF or the rate limit is answered before it reaches `MetricsMiddleware`, so those 413, 403 and 429 responses never show up in the HTTP metrics. They still get CORS and security headers, since those two sit further out. Domain exceptions are turned into responses by the exception handlers inside the app, so every middleware sees them as normal responses.

## CORS

Starlette's `CORSMiddleware` allows the origins in `CORS_ORIGINS` with credentials, the methods GET, POST, PUT, DELETE and PATCH, and request headers including `X-CSRF-Token`. It exposes `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` and `Retry-After` so the browser can read them.

## Cache control

`CacheControlMiddleware` sets `Cache-Control` on GET responses with status 200 whose path matches one of these prefixes:

```python
--8<-- "backend/app/core/middlewares/cache.py:cache_policies"
```

An exact match wins, otherwise the first key the path starts with. So everything under `/api/v1/notifications` is `private, no-cache`. Public entries also get `Vary: Accept-Encoding`. Other paths are left alone. The login and `/api/v1/auth/me` routes set `Cache-Control: no-store` themselves.

## Security headers

`SecurityHeadersMiddleware` adds the same five headers to every HTTP response:

| Header | Value |
|--------|-------|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains` |
| `Content-Security-Policy` | `default-src 'self'; frame-ancestors 'none'` |

These cover the API responses. The SPA's own CSP comes from nginx.

## Request size limit

`RequestSizeLimitMiddleware` rejects bodies over 10 MB. `main.py` doesn't pass `max_size_mb`, so the default applies:

```python
--8<-- "backend/app/core/middlewares/request_size_limit.py:RequestSizeLimitMiddleware"
```

It checks two things. A `Content-Length` above the limit is rejected with 413 before the body is read:

```json
{"detail": "Request too large. Maximum size is 10.0MB"}
```

Then it wraps `receive` and counts bytes as they stream in, which catches chunked uploads that send no `Content-Length`. Reading stops as soon as the count passes the limit. The status differs, though: on routes that parse a body, FastAPI catches the exception while parsing and answers 400 with "There was an error parsing the body" instead of 413.

## CSRF

`CSRFMiddleware` enforces the double-submit check on state-changing `/api/` requests from logged-in browsers. It gets `SecurityService` from the Dishka container and answers 403 with `{"detail": "CSRF validation failed"}` on failure. The rules and exemptions are on the [Authentication](authentication.md#csrf) page.

## Rate limit

`RateLimitMiddleware` checks each request against Redis, keyed by client IP, and adds `X-RateLimit-*` headers or answers 429. It skips these paths:

```python
--8<-- "backend/app/core/middlewares/rate_limit.py:excluded_paths"
```

[Rate limiting](rate-limiting.md) has the rules, the key format and the known gaps.

## Metrics

`MetricsMiddleware` records HTTP telemetry through the OpenTelemetry API:

```python
--8<-- "backend/app/core/middlewares/metrics.py:instruments"
```

Count, duration and response size are labelled with method, path template and status, the other two with method and path template only. The path template replaces UUIDs, numeric segments and MongoDB ObjectIds with `{id}` to keep cardinality down:

```python
--8<-- "backend/app/core/middlewares/metrics.py:path_template"
```

Request size comes from `Content-Length` and is only recorded when the header is present, the same for response size. The `/metrics` path is skipped. If a route raises an exception no handler maps, the middleware records nothing for that request and `http_requests_active` stays incremented.

`setup_metrics` installs the OTLP exporter, exporting every 60 seconds, only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Otherwise the instruments use the no-op provider. When it does run, it also registers three process-level gauges:

```python
--8<-- "backend/app/core/middlewares/metrics.py:system_metrics"
```

`system_memory_bytes` reports used, available and percent, `system_cpu_percent` the host CPU, and `process_metrics` the process RSS, VMS, CPU and thread count.
