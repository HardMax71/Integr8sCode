# Deployment

Everything runs from one docker-compose.yaml: the backend, the frontend, six workers, MongoDB, Redis, Kafka and the optional observability stack. The workers reuse the backend image with a different `command:`, so there is one application image to build. Kubernetes only runs the executor pods; the backend and workers reach it through a kubeconfig that the cert-generator container writes.

`backend/Dockerfile.base` is a two-stage build on `python:3.14-slim`. The builder stage runs `uv sync --locked --no-dev --no-install-project --no-build`, and the final stage copies only the virtualenv plus a few runtime libraries. `backend/Dockerfile` adds the application code on top and starts gunicorn with uvicorn workers on port 443. The frontend image builds the Svelte app with `node:26-alpine` and serves it from `nginx:1.31-alpine`, see [Nginx configuration](nginx-configuration.md).

## deploy.sh

[deploy.sh](https://github.com/HardMax71/Integr8sCode/blob/main/deploy.sh) is a thin wrapper around Docker Compose:

```bash
--8<-- "deploy.sh:usage"
```

`check` and `test` are broken right now ([#292](https://github.com/HardMax71/Integr8sCode/issues/292)). `test` runs `pytest tests/integration`, a directory that no longer exists, and `check` calls `uv run bandit`, which isn't installed in any dependency group. Use the commands in [CI/CD](cicd.md#running-checks-locally) instead.

## Local stack

```bash
./deploy.sh dev                  # core stack
./deploy.sh dev --observability  # plus Grafana, Jaeger, Loki, Victoria Metrics, OTel Collector
./deploy.sh dev --debug          # all of the above plus Kafdrop
```

The core stack is MongoDB, Redis, Kafka (KRaft, no ZooKeeper), the backend, the frontend and the six workers. A few one-shot containers run first and exit: `shared-ca` prepares the shared CA volume, `cert-generator` writes TLS certs and `backend/kubeconfig.yaml`, and `user-seed` creates the default accounts. Kafka creates topics on first use (`KAFKA_AUTO_CREATE_TOPICS_ENABLE`). Topic names are the event types themselves, such as `execution_requested`, with no prefix.

| Service            | URL                     | Needs                         |
|--------------------|-------------------------|-------------------------------|
| Frontend           | https://localhost:5001  |                               |
| Backend API        | https://localhost:443   |                               |
| Kafka (host)       | localhost:9092          |                               |
| MongoDB            | 127.0.0.1:27017         |                               |
| Redis              | 127.0.0.1:6379          |                               |
| Grafana            | http://localhost:3000   | `--observability` or `--debug` |
| Jaeger UI          | http://localhost:16686  | `--observability` or `--debug` |
| Victoria Metrics   | http://localhost:8428   | `--observability` or `--debug` |
| Loki               | http://localhost:3100   | `--observability` or `--debug` |
| Kafdrop            | http://localhost:9000   | `--debug`                     |

Inside the compose network Kafka is `kafka:29092`. From the host use `localhost:9092`, since that's the listener advertised for host clients.

The seed job creates `user` / `user123` and `admin` / `admin123`. Override the passwords with env vars:

```bash
DEFAULT_USER_PASSWORD=mypass ADMIN_USER_PASSWORD=myadmin ./deploy.sh dev
```

There's no hot reload. Gunicorn runs without `--reload` and the frontend is an nginx production build. The backend and workers bind-mount `backend/app` and `backend/workers`, so a Python change needs `docker compose restart backend` (and the affected workers). A frontend change needs `docker compose up -d --build frontend`.

Data lives in named volumes:

```yaml
--8<-- "docker-compose.yaml:dev_volumes"
```

`./deploy.sh down` stops the stack and keeps them. `docker compose down -v` deletes them too.

## Healthchecks

| Service          | Healthcheck                                                                 |
|------------------|-----------------------------------------------------------------------------|
| MongoDB          | `mongosh` ping, with the root credentials read from the container env       |
| Redis            | `redis-cli -a $REDIS_PASSWORD ping`                                         |
| Kafka            | `kafka-broker-api-versions --bootstrap-server localhost:9092`               |
| Backend          | `curl -k https://localhost:443/api/v1/health/live`                          |
| Frontend         | `curl -k https://localhost:5001`                                            |
| Grafana          | `curl localhost:3000/api/health`                                            |
| Victoria Metrics | `wget http://127.0.0.1:8428/-/healthy`                                      |

Loki has none because its image is distroless and has no shell, so Grafana and the collector wait for `service_started`. Jaeger, the OTel Collector, Kafdrop and the workers have no healthcheck either.

## Memory limits

Every long-running service except Kafdrop has a `mem_limit`.

| Service              | `mem_limit` | Notes                                                       |
|----------------------|-------------|-------------------------------------------------------------|
| MongoDB              | 1024m       | `--wiredTigerCacheSizeGB 0.4`                               |
| Redis                | 300m        | `--maxmemory 256mb`, `allkeys-lru`, persistence off         |
| Kafka                | 1280m       | `-Xms256m -Xmx1g`                                           |
| Backend              | 768m        | `WEB_CONCURRENCY` gunicorn workers (default 2)              |
| Frontend             | 128m        |                                                             |
| Each of six workers  | 160m        |                                                             |
| Grafana              | 512m        | Grafana 13 idles near 300 MiB                               |
| Jaeger               | 256m        | in-memory storage                                           |
| Loki                 | 256m        |                                                             |
| Victoria Metrics     | 256m        | `--retentionPeriod=30d`                                     |
| OTel Collector       | 192m        | `memory_limiter` at 150 MiB                                 |

Kafdrop runs with `-Xmx512M` and no limit. All services above except Jaeger have `restart: unless-stopped`.

## Observability profile

The `observability` profile adds a one-shot `mongo-monitor-user` container. It connects as root and creates (or updates) an `otelMonitor` role with `serverStatus`, `top`, `dbStats`, `indexStats` and `listCollections`, plus a user with only that role. The collector's mongodb receiver logs in as that user, since root fails `$indexStats` on `admin.system.*`. Set the credentials with `MONGO_MONITOR_USER` (default `otel-monitor`) and `MONGO_MONITOR_PASSWORD` (default `monitorpassword`).

Grafana starts through a small entrypoint. It resets the admin password from `GF_SECURITY_ADMIN_PASSWORD`, starts Grafana without the alert rules, waits until the dashboard provider has created the `integr8scode` folder, then copies the rules back and calls the alerting reload API. Loaded first, the rules would create their own folder with a random UID. See [Grafana integration](grafana-integration.md).

The frontend gets `GRAFANA_PUBLIC_URL` from `GRAFANA_ROOT_URL` (default `http://localhost:3000/`), which is where `/grafana` on the app host redirects.

## Image versions

| Image                                  | Version   |
|----------------------------------------|-----------|
| `mongo`                                | 9.0.2     |
| `redis`                                | 8.10.2-alpine |
| `confluentinc/cp-kafka`                | 8.3.2     |
| `grafana/grafana`                      | 13.2.3    |
| `jaegertracing/jaeger`                 | 2.20.0    |
| `grafana/loki`                         | 3.7.8     |
| `victoriametrics/victoria-metrics`     | v1.153.0  |
| `otel/opentelemetry-collector-contrib` | 0.162.0   |
| `obsidiandynamics/kafdrop`             | 4.3.0     |

Jaeger stays on 2.20.0 because 2.21 removed the search API that Grafana's Jaeger datasource calls ([grafana/grafana#112336](https://github.com/grafana/grafana/issues/112336)). Dependabot ignores newer Jaeger versions until that ships.

MongoDB 9 starts fine on a volume created by 8.0 but keeps the feature compatibility version at 8.0. Raise it once you're sure you won't roll back:

```bash
docker compose exec mongo sh -c 'mongosh -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval "db.adminCommand({ setFeatureCompatibilityVersion: \"9.0\", confirm: true })"'
```

## Troubleshooting

| Issue                 | Cause                              | Fix                                                         |
|-----------------------|------------------------------------|-------------------------------------------------------------|
| Unknown topic errors  | Kafka not ready yet                | `docker compose logs kafka`                                 |
| MongoDB auth errors   | Volume created with other credentials | `MONGO_USER`/`MONGO_PASSWORD` must match what the volume was initialized with |
| Workers can't reach k8s | Stale or expired kubeconfig (the token lasts 24h) | `docker compose restart cert-generator`, then restart the workers |

List topics from inside the broker:

```bash
docker compose exec kafka kafka-topics --list --bootstrap-server localhost:9092
```

### k3s crash loop after a VPN or IP change

When the host IP changes (VPN on or off, new network, DHCP renewal), k3s keeps the old IP in its datastore under `/var/lib/rancher/k3s/server/db/` and in the certificate SANs under `/var/lib/rancher/k3s/server/tls/`. It then crash-loops: `systemctl status k3s` shows `activating (auto-restart)` and `kubectl` gets `connection refused`.

!!! warning "This deletes all cluster state"
    The fix wipes every workload, namespace, secret and local-path volume in the cluster. Take an etcd snapshot (`sudo k3s etcd-snapshot save`) and back up anything you need first.

```bash
sudo systemctl stop k3s
sudo rm -rf /var/lib/rancher/k3s/server/db/ /var/lib/rancher/k3s/server/tls/
sudo systemctl start k3s

# regenerate the kubeconfig and reconnect the workers
docker compose restart cert-generator
docker compose restart k8s-worker pod-monitor
```

The cluster comes back empty, so Kueue and the `integr8scode` namespace are recreated by cert-generator on that restart. With NordVPN, `nordvpn set lan-discovery enabled` keeps the host reachable from containers. See [k3s#277](https://github.com/k3s-io/k3s/issues/277) and the [k3s certificate docs](https://docs.k3s.io/cli/certificate).

## Pre-built images

Stack Tests builds `base`, `backend`, `frontend` and `cert-generator` and pushes them to GHCR as `sha-<7 chars>`. On `main`, after the Trivy scan job, they're also tagged `latest`, and each release adds a CalVer tag such as `2026.10.0`. To run them instead of building:

```bash
IMAGE_TAG=sha-abc1234 docker compose up -d --no-build
```

## Production

Merges to `main` that trigger Stack Tests deploy automatically: Stack Tests, then Docker Scan & Promote, then [Release & Deploy](cicd.md#release-deploy). The deploy job SSHes into the server, runs `git pull` in `/opt/Integr8sCode`, logs in to GHCR and exports the secrets from the repo (`SECRET_KEY`, `MONGO_USER`, `MONGO_PASSWORD`, `MONGO_MONITOR_PASSWORD`, `REDIS_PASSWORD`, the Grafana and Mailjet values) together with `COMPOSE_PROFILES=observability` and `GRAFANA_ROOT_URL=https://grafana.integr8scode.cc/`. Then it runs:

```bash
docker compose pull
docker compose up -d --remove-orphans --no-build --wait --wait-timeout 180
docker image prune -af --filter "until=72h"
```

To roll back by hand, set `IMAGE_TAG` to an older CalVer or SHA tag and run the same `pull` and `up`. Export the same variables the deploy job does first. Without them compose recreates the containers with the dev defaults.

To set up the server and the repository secrets, see [Required secrets](cicd.md#required-secrets).
