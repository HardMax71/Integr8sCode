# Nginx configuration

The frontend container is nginx. It serves the Svelte build, proxies `/api/` to the backend and `/otlp/v1/logs` to the collector, and has a second server block that proxies Grafana on its own hostname. The config is [`frontend/nginx.conf.template`](https://github.com/HardMax71/Integr8sCode/blob/main/frontend/nginx.conf.template).

```mermaid
flowchart LR
    Browser -->|"app host :5001"| App["server _"]
    Browser -->|"grafana.integr8scode.cc :5001"| G["server grafana.integr8scode.cc"]
    App -->|"/api/*"| Backend["${BACKEND_URL}"]
    App -->|"/otlp/v1/logs"| Collector["otel-collector:4319"]
    App -->|"/grafana"| Redirect["302 to ${GRAFANA_PUBLIC_URL}"]
    App -->|"everything else"| Static["static files, SPA fallback"]
    G --> Grafana["${GRAFANA_URL}"]
```

## App server

```nginx
--8<-- "frontend/nginx.conf.template:server_block"
```

Both server blocks listen on `5001 ssl` with `/etc/nginx/certs/server.crt` and `server.key`. Mount your own pair there and nginx uses it; otherwise a script the image puts in `/docker-entrypoint.d/` makes a self-signed pair before nginx starts and keeps it for the container's lifetime. Compose publishes the port as `5001:5001`. In production the host's firewall lets only Cloudflare's ranges reach it, so every visitor comes through Cloudflare.

### Client addresses and logging

```nginx
--8<-- "frontend/nginx.conf.template:client_address"
```

Behind Cloudflare every connection comes from a Cloudflare address. `set_real_ip_from` lists Cloudflare's published ranges, and `real_ip_header CF-Connecting-IP` makes nginx take the visitor's address from that header on connections from those ranges only. A connection from anywhere else keeps its own address whatever headers it sends. Everything after that sees the visitor: the access log, the browser-log rate limit below, and the `X-Real-IP` and `X-Forwarded-For` headers nginx sends upstream. Both carry `$remote_addr` alone, so an `X-Forwarded-For` a client made up never reaches the backend's rate limiter. Cloudflare changes the list rarely; [cloudflare.com/ips](https://www.cloudflare.com/ips/) has the current one.

`log_not_found off` keeps requests for missing files out of the error log; they're still 404s in the access log. Before it, every scanner probing for `/wp-includes/` or `/firebaseConfig.js` wrote an `[error]` line, and the [error-lines alert](grafana-integration.md#alerting) mailed it.

### Security headers

```nginx
--8<-- "frontend/nginx.conf.template:security_headers"
```

There are six headers: CSP, HSTS, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy` and `Permissions-Policy`. Only HSTS has `always`, so it's the only one nginx also sends on 4xx and 5xx responses.

The page's real CSP isn't here. SvelteKit writes it into `200.html` as a `<meta>` tag with a hash of its inline bootstrap script, from the `csp` option in `vite.config.ts`; [Frontend build](../architecture/frontend-build.md#configuration) has the policy. A meta CSP can't carry `frame-ancestors`, so nginx sends just that directive as a header. The browser enforces both.

```nginx
--8<-- "frontend/nginx.conf.template:nonce_injection"
```

The meta CSP allows one nonce for `<style>` tags, the one CodeMirror puts on its theme. `200.html` ships with a `**CSP_NONCE**` placeholder in the policy and in a `csp-nonce` meta tag, and `sub_filter` swaps in `$request_id`, so every response gets a fresh value. HTML is served with `expires -1`, so a cached page never reuses an old nonce.

No `location` block uses `add_header`. That's on purpose: one `add_header` inside a location drops every `add_header` inherited from the `server` block, so the security headers would disappear from that location. If a location ever needs its own response header, it has to repeat all six. `proxy_set_header` has the same all-or-nothing inheritance, which is why the SSE location repeats the proxy headers of `/api/`.

### Compression

```nginx
--8<-- "frontend/nginx.conf.template:compression"
```

Text types only. Images other than SVG and icons are already compressed.

### API proxy and SSE

```nginx
--8<-- "frontend/nginx.conf.template:api_proxy"
```

```nginx
--8<-- "frontend/nginx.conf.template:sse_proxy"
```

The backend's address goes through a variable and Docker's resolver, like Grafana's below, so nginx looks `backend` up again every 30 seconds. With a plain `proxy_pass https://backend:443`, nginx resolves it once at startup. A backend that comes back with a new IP, for example after a Docker restart, then gets 502 until the frontend restarts too.

`proxy_ssl_verify on` checks the backend's certificate on every request. The backend makes that certificate when it first starts and keeps it in the `backend_tls_cert` volume, nginx mounts the volume read-only, and `proxy_ssl_trusted_certificate` trusts exactly that file, so a different server answering as `backend` gets a 502. The frontend waits for the backend's healthcheck, since nginx reads the file only when it starts.

The SSE location under `/api/v1/events/` speaks HTTP/1.1 with an empty `Connection` header, turns off buffering and caching, and raises both timeouts to 24 hours so long-lived streams aren't cut after the default 60 seconds. `proxy_buffering off` alone is enough to pass each event through as it arrives.

### Browser logs

```nginx
--8<-- "frontend/nginx.conf.template:browser_logs"
```

The app sends its log records here as OTLP JSON, at most one batch a second, and nginx passes them to the collector's `otlp/browser` receiver ([Loki](loki.md#collector) has the rest of the path). Anyone can post to this path, so it takes POST only, bodies up to 64 KB, and 30 requests a minute per visitor address with a burst of 30, from the `limit_req_zone` at the top of the file; past that nginx answers 429. The upstream goes through a variable like the backend's, so nginx starts while the collector is down and this path returns 502 until it's back.

### Static files and SPA routing

```nginx
--8<-- "frontend/nginx.conf.template:static_caching"
```

SvelteKit writes the JavaScript and CSS under `_app/immutable/` with content hashes in their names, so a year of caching is safe. HTML gets `expires -1` so the browser always fetches the current asset names. Every other path goes to `location /`, which serves `200.html` when no file matches and lets the SvelteKit router handle the path. A missing file with one of the asset or `.html` extensions above gets a 404 instead, since its regex location has no fallback.

`location = /grafana` returns a 302 to `${GRAFANA_PUBLIC_URL}`. There's no `/grafana/` subpath proxy.

## Grafana server

```nginx
--8<-- "frontend/nginx.conf.template:grafana_proxy"
```

Grafana gets its own hostname, `grafana.integr8scode.cc`, and is proxied at the root. grafana.ini sets no `root_url`; compose passes `GF_SERVER_ROOT_URL` from `GRAFANA_ROOT_URL`. `/api/live/` is the Grafana Live websocket, so it gets the `Upgrade` and `Connection` headers.

The upstream goes through a variable with Docker's resolver (`127.0.0.11`), so nginx resolves `grafana` per request instead of at startup. Without that, nginx would refuse to start while Grafana is down. In that case the Grafana host just returns 502. This server block sets no security headers.

## Environment variables

The nginx image runs `envsubst` on `/etc/nginx/templates/*.template` at startup and only replaces variables that are set, so nginx's own `$host` or `$request_id` stay intact.

```dockerfile
--8<-- "frontend/Dockerfile:production_stage"
```

| Variable             | Compose value                                     | Used for                     |
|----------------------|---------------------------------------------------|------------------------------|
| `BACKEND_URL`        | `https://backend:443`                             | `/api/` proxy                |
| `GRAFANA_URL`        | `${GRAFANA_URL:-http://grafana:3000}`             | Grafana server upstream      |
| `GRAFANA_PUBLIC_URL` | `${GRAFANA_ROOT_URL:-http://localhost:3000/}`     | `/grafana` redirect target   |

## Applying changes

The template is baked into the image, so rebuild and recreate:

```bash
docker compose up -d --build frontend
```

`docker compose restart frontend` keeps the old container and the old image, so it doesn't pick up a change. With pre-built images, `docker compose pull frontend` followed by `docker compose up -d frontend` does the same.

## Troubleshooting

| Issue                                  | Likely cause                                  |
|----------------------------------------|-----------------------------------------------|
| SSE events arrive in batches or stop   | SSE location missing `proxy_buffering off` or the 24h timeouts |
| CSP blocks a resource                  | Source missing from the `csp` directives in `vite.config.ts`; the browser console names the directive |
| 502 on `/api/`                         | Backend down: `docker compose logs backend`   |
| 502 on the Grafana host                | Observability profile not running             |
| Security headers missing on a route    | An `add_header` in that location; check with `curl -kI` |
