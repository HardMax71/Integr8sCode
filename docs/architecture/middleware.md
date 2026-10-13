# Middleware

`create_app` in `app/main.py` adds six ASGI middlewares. Starlette's `add_middleware` puts each new one outside the previous ones, so the last one added runs first. A request passes through them in this order, and the response comes back in reverse:

1. `CORSMiddleware`
2. `CacheControlMiddleware`
3. `SecurityHeadersMiddleware`
4. `RequestSizeLimitMiddleware`
5. `CSRFMiddleware`
6. `RateLimitMiddleware`

The OpenTelemetry FastAPI instrumentation wraps all six from the outside, so its HTTP metrics and spans include the 403, 429 and 413 responses that the CSRF, rate limit and size checks answer with. Those responses still get CORS and security headers, since those two sit further out. Domain exceptions are turned into responses by the exception handlers inside the app, so every middleware sees them as normal responses.

## CORS

Starlette's `CORSMiddleware` allows the origins in `CORS_ORIGINS` with credentials, the methods GET, POST, PUT, DELETE and PATCH, and request headers including `X-CSRF-Token`. It exposes `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` and `Retry-After` so the browser can read them.

## Cache control

`CacheControlMiddleware` sets `Cache-Control` on GET responses with status 200 whose path matches one of these prefixes:

```python
--8<-- "backend/app/core/middlewares/cache.py:cache_policies"
```

An exact match wins, otherwise the first key the path starts with. So everything under `/api/v1/notifications` is `private, no-cache`. Public entries also get `Vary: Accept-Encoding`. Other paths are left alone. The login and `/api/v1/auth/me` routes set `Cache-Control: no-store` themselves.

## Security headers

`SecurityHeadersMiddleware` adds the same five headers to every HTTP response that passes back through it:

| Header | Value |
|--------|-------|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains` |
| `Content-Security-Policy` | `default-src 'self'; frame-ancestors 'none'` |

Two kinds of response never pass through it: a CORS preflight, which `CORSMiddleware` answers further out, and the bare 500 that Starlette's outermost error handler sends for an exception nothing maps. These headers cover the other API responses. The SPA's own CSP comes from nginx.

## Request size limit

`RequestSizeLimitMiddleware` rejects bodies over 10 MB. `main.py` doesn't pass `max_size_mb`, so the default applies:

```python
--8<-- "backend/app/core/middlewares/request_size_limit.py:RequestSizeLimitMiddleware"
```

It checks two things. A `Content-Length` above the limit is rejected with 413 before the body is read:

```json
{"status": 413, "detail": "Request too large. Maximum size is 10.0MB"}
```

Then it wraps `receive` and counts bytes as they stream in, which catches chunked uploads that send no `Content-Length`. Reading stops as soon as the count passes the limit, with an `HTTPException` that the app answers as 413 with the same body. It has to be that exception: FastAPI turns anything else raised while it reads a body into a 400.

## CSRF

`CSRFMiddleware` enforces the double-submit check on state-changing `/api/` requests from logged-in browsers. It gets `SecurityService` from the Dishka container and answers 403 with `{"status": 403, "detail": "CSRF validation failed"}` on failure. The rules and exemptions are on the [Authentication](authentication.md#csrf) page.

## Rate limit

`RateLimitMiddleware` checks each request against Redis, keyed by the user id from a valid access token or else by client IP, and adds `X-RateLimit-*` headers or answers 429. It skips these paths:

```python
--8<-- "backend/app/core/middlewares/rate_limit.py:excluded_paths"
```

[Rate limiting](rate-limiting.md) has the rules, the key format and the known gaps.

## Metrics

No middleware of ours measures HTTP. `create_app` calls `FastAPIInstrumentor().instrument_app` from `opentelemetry-instrumentation-fastapi`, which records every request except health, metrics, docs and `openapi.json` as `http.server.request.duration`, `http.server.active_requests` and the request and response body sizes, labelled by method, FastAPI route template and status code. It has to run in `create_app`: Starlette builds the middleware stack on its first ASGI call, which is the lifespan's, and an instrumentation added after that never runs. The backend image sets `OTEL_SEMCONV_STABILITY_OPT_IN=http`, so the names follow the stable HTTP semantic conventions.

`setup_metrics` installs the OTLP exporter, exporting every 60 seconds, only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Otherwise every instrument uses the no-op provider. It also starts `opentelemetry-instrumentation-system-metrics` for the process's own CPU, memory, threads and file descriptors. The host's CPU and memory come from the collector's `host_metrics` receiver instead.
