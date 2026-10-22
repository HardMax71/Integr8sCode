# Deployment

Everything runs from one docker-compose.yaml: the backend, the frontend, the worker, MongoDB, Redis, Kafka and the optional observability stack. The worker reuses the backend image with a different `command:`, so there is one application image to build. Kubernetes only runs the executor pods. The worker reads k3s's own kubeconfig from `/etc/rancher/k3s`, reaches the API at `host.docker.internal:6443` and on start creates the `integr8scode` namespace with its Pod Security labels, NetworkPolicy and ResourceQuota.

`backend/Dockerfile` builds on `python:3.14-slim` in three stages. The builder stage runs `uv sync --locked --no-dev --no-install-project --no-build`, the `base` stage copies only the virtualenv plus a few runtime libraries, and the last stage adds the application code. On first start the container makes a self-signed certificate and keeps it in the `backend_tls_key` and `backend_tls_cert` volumes, then it seeds the default users and starts gunicorn with uvicorn workers on port 443 over TLS. nginx mounts the certificate volume and verifies the backend against it. The frontend image builds the Svelte app with `node:26-alpine` and serves it from `nginx:1.31-alpine`, see [Nginx configuration](nginx-configuration.md).

## deploy.sh

[deploy.sh](https://github.com/HardMax71/Integr8sCode/blob/main/deploy.sh) is a thin wrapper around Docker Compose:

```bash
--8<-- "deploy.sh:usage"
```

`check` runs the static CI gates on the host: ruff, `mypy --strict`, the orphan module check and bandit. `test` runs the unit and Grafana contract tests on the host, then starts the stack with `BACKEND_CONFIG=config.test.toml` and runs the e2e suite inside the backend container. That variable makes the backend and the worker mount config.test.toml as their config.toml, the way CI copies it over. [CI/CD](cicd.md#running-checks-locally) lists the same commands one by one.

## Local stack

```bash
./deploy.sh dev                  # core stack
./deploy.sh dev --observability  # plus Grafana, Jaeger, Loki, Victoria Metrics, OTel Collector, host-metrics
./deploy.sh dev --debug          # all of the above plus Kafdrop
```

The core stack is MongoDB, Redis, Kafka (KRaft, no ZooKeeper), the backend, the frontend and the worker. No container runs once and exits. Secrets come from `.env`, which `./deploy.sh dev` copies from `.env.example` on its first run; compose has no defaults for them and refuses to start while one is empty. Kafka creates topics on first use (`KAFKA_AUTO_CREATE_TOPICS_ENABLE`). Topic names are the event types themselves, such as `execution_requested`, with no prefix.

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

Every time the backend starts, it creates `user` / `user123` and `admin` / `admin123` with `scripts/seed_users.py`, and sets the passwords of accounts that already exist again. The passwords are `DEFAULT_USER_PASSWORD` and `ADMIN_USER_PASSWORD` in `.env`.

There's no hot reload. Gunicorn runs without `--reload` and the frontend is an nginx production build. The backend and the worker bind-mount `backend/app`, so a Python change needs `docker compose restart backend worker`. A frontend change needs `docker compose up -d --build frontend`.

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
| Backend          | `curl --cacert /app/certs/cert/server.crt https://localhost:443/api/v1/health/live` |
| Frontend         | `curl -k https://localhost:5001`                                            |
| Grafana          | `curl localhost:3000/api/health`                                            |
| Victoria Metrics | `wget http://127.0.0.1:8428/-/healthy`                                      |

Loki has none because its image is distroless and has no shell, so Grafana and the collector wait for `service_started`. Jaeger, the OTel Collector, host-metrics, Kafdrop and the worker have no healthcheck either.

## Memory limits

Every long-running service except Kafdrop has a `mem_limit`.

| Service              | `mem_limit` | Notes                                                       |
|----------------------|-------------|-------------------------------------------------------------|
| MongoDB              | 1024m       | `--wiredTigerCacheSizeGB 0.4`                               |
| Redis                | 300m        | `--maxmemory 256mb`, `allkeys-lru`, persistence off         |
| Kafka                | 1280m       | `-Xms256m -Xmx1g`                                           |
| Backend              | 768m        | `WEB_CONCURRENCY` gunicorn workers (default 2)              |
| Frontend             | 128m        |                                                             |
| Worker               | 256m        | idles near 150 MiB                                          |
| Grafana              | 512m        | Grafana 13 idles near 300 MiB                               |
| Jaeger               | 256m        | in-memory storage                                           |
| Loki                 | 256m        |                                                             |
| Victoria Metrics     | 256m        | `--retentionPeriod=30d`                                     |
| OTel Collector       | 192m        | `memory_limiter` at 150 MiB                                 |
| host-metrics         | 128m        | `memory_limiter` at 100 MiB; idles near 57 MiB              |

Kafdrop runs with `-Xmx512M` and no limit. All services above except Jaeger have `restart: unless-stopped`.

## Observability profile

The backend's start creates (or updates) an `otelMonitor` role with `serverStatus`, `top`, `dbStats`, `indexStats` and `listCollections`, plus a user with only that role. The collector's mongodb receiver logs in as that user, since root fails `$indexStats` on `admin.system.*`. The credentials are `MONGO_MONITOR_USER` (default `otel-monitor`) and `MONGO_MONITOR_PASSWORD` in `.env`. Until the backend has run, the receiver's scrapes fail and retry.

host-metrics runs with `network_mode: host`, so its network scraper reads the host's interfaces, and it reaches the collector through the port compose publishes on `127.0.0.1:4317`. It has no ports of its own: `otel-host-metrics.yaml` turns its internal metrics off and runs no extensions.

Grafana starts through a small entrypoint. It resets the admin password from `GF_SECURITY_ADMIN_PASSWORD`, starts Grafana without the alert rules, waits until the dashboard provider has created the `integr8scode` folder, then copies the rules back and calls the alerting reload API. Loaded first, the rules would create their own folder with a random UID. See [Grafana integration](grafana-integration.md).

The frontend gets `GRAFANA_PUBLIC_URL` from `GRAFANA_ROOT_URL` (default `http://localhost:3000/`), which is where `/grafana` on the app host redirects.

## Image versions

| Image                                  | Version   |
|----------------------------------------|-----------|
| `mongo`                                | 9.0.4     |
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
| Worker can't reach k8s | k3s was reinstalled and wrote a new kubeconfig | `docker compose restart worker` |

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

# reconnect the worker with the new kubeconfig
docker compose restart worker
```

The cluster comes back empty, and the worker recreates the `integr8scode` namespace, its NetworkPolicy and ResourceQuota when it restarts. With NordVPN, `nordvpn set lan-discovery enabled` keeps the host reachable from containers. See [k3s#277](https://github.com/k3s-io/k3s/issues/277) and the [k3s certificate docs](https://docs.k3s.io/cli/certificate).

### k3s certificates expired

k3s issues its certificates for a year and renews them only when it starts. On a server that runs longer than that without a restart, kubectl and the worker fail with `x509: certificate has expired`. `sudo systemctl restart k3s` renews them, then `docker compose restart worker`, since the worker reads k3s's kubeconfig, client certificate included, only when it starts. If k3s then hangs in `activating` and its journal repeats `dynamiclistener [::]:6443: failed to update cert with connection local address: EOF`, the cached serving certificate in /var/lib/rancher/k3s/server/tls/dynamic-cert.json is empty, which happens when the disk fills up. Move that file aside and start k3s again; it writes a new one.

## Pre-built images

CI builds `backend` and `frontend` and pushes them to GHCR as `sha-<7 chars>`. On `main`, after the Trivy scan job, they're also tagged `latest`, and each release adds a CalVer tag such as `2026.10.0`. To run them instead of building:

```bash
IMAGE_TAG=sha-abc1234 docker compose up -d --no-build
```

## Production

Production gets one release a day. Every merge to `main` goes through CI and Docker Scan & Promote, which moves `latest`; at 23:00 Europe/Berlin [Release & Deploy](cicd.md#release-deploy) releases whatever `latest` is and deploys it, and skips the night when nothing new passed. The deploy job SSHes into the server, removes images no container uses, checks out the release's git tag in `/opt/Integr8sCode` (so the compose file and config match the images) and writes `/opt/Integr8sCode/.env` (mode 600) from the repo's secrets (`SECRET_KEY`, `MONGO_USER`, `MONGO_PASSWORD`, `MONGO_MONITOR_PASSWORD`, `REDIS_PASSWORD`, `ADMIN_USER_PASSWORD`, `DEFAULT_USER_PASSWORD`, the Grafana and Mailjet values) together with `IMAGE_TAG`, `COMPOSE_PROFILES=observability` and `GRAFANA_ROOT_URL=https://grafana.integr8scode.cc/`. Compose reads that file for every command, so the backup cron and commands run by hand on the server use the same values, and a secret that came through empty stops compose before anything starts. The values sit in single quotes, so a secret can't contain one. Then it runs:

```bash
docker compose pull
docker compose up -d --remove-orphans --no-build --wait --wait-timeout 180
docker image prune -af
```

Between `up` and the prune it restarts the collector, host-metrics, VictoriaMetrics, Loki or Grafana when the release changed a config file that service mounts, comparing the new tag with the commit the server ran before. They read their config only when they start, and compose recreates a container only when its service definition changes, never for a new file behind a mount. Without the restart, a release that changes only `otel-collector-config.yaml` keeps running the old one; release 2026.10.28 ran 2.5 hours like that, without its new span metrics. Grafana re-reads its dashboards every 10 seconds by itself, so a dashboard change doesn't restart it.

Pruning before the pull and after the deploy keeps only the images the running stack uses. To roll back by hand, check out one of the two CalVer tags before the current one (older releases are deleted, and so are their images), set `IMAGE_TAG` in `.env` to it and run the same `pull` and `up`, plus `docker compose restart` for any of those four whose config the rollback changes; the old images come back from GHCR.

The images on GHCR are public, so the server pulls them without logging in. To set up the server and the repository secrets, see [Required secrets](cicd.md#required-secrets).

Every service logs through Docker's `fluentd` driver to the collector, which passes the lines to Loki ([Log aggregation](loki.md)), set once as `x-logging` at the top of docker-compose.yaml. Docker keeps a local copy for `docker logs` of at most 3 files of 10MB per container (`cache-max-size`, `cache-max-file`), and the collector itself uses the `local` driver with the same limits. The default `json-file` driver never rotates, and its logs once filled the production disk.

`./deploy.sh backup` dumps MongoDB as a gzip archive into /var/backups/mongo (or the directory you pass), skips the run when less than 5G is free there, and deletes dumps older than 14 days. Production runs it every night from /etc/cron.d/integr8scode-backup:

```text
30 3 * * * root /opt/Integr8sCode/deploy.sh backup >> /var/log/integr8scode-backup.log 2>&1
```

The dumps sit on the same disk as the database, so they cover a bad write or a failed upgrade, not a lost server. To restore one:

```bash
docker compose exec -T mongo sh -c 'mongorestore -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --archive --gzip --drop' < /var/backups/mongo/mongo-2026-10-13.archive.gz
```
