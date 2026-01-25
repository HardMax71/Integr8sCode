# Getting Started

This guide walks you through running Integr8sCode locally and executing your first script. You'll need Docker and Docker Compose installed - that's it.

## What you're deploying

The full stack includes a Svelte frontend, FastAPI backend, MongoDB, Redis, Kafka with Schema Registry, and seven background workers. Sounds like a lot, but `docker compose` handles all of it. First startup takes a few minutes to pull images and initialize services; subsequent starts are much faster.

## Start the stack

```bash
git clone https://github.com/HardMax71/Integr8sCode.git
cd Integr8sCode
./deploy.sh dev
```

Wait for the services to come up. You can watch progress with `docker compose logs -f` in another terminal. When you see the backend responding to health checks, you're ready.

Verify everything is running:

```bash
curl -k https://localhost/api/v1/health/live
```

If everything is up, you'll get:

```json
{"status":"ok","uptime_seconds":42,"timestamp":"2025-01-25T12:00:00Z"}
```

## Access the UI

Open [https://localhost:5001](https://localhost:5001) in your browser. You'll get a certificate warning since it's a self-signed cert - accept it and continue.

Log in with the default credentials:

- **Username:** `user`
- **Password:** `user123`

For admin access (user management, system settings, event browser), use `admin` / `admin123`.

!!! warning "Development only"
    These credentials are seeded automatically for local development. For production, set `DEFAULT_USER_PASSWORD` and `ADMIN_USER_PASSWORD` environment variables before deploying.

## Run your first script

The editor opens with a Python example. Click **Run** to execute it. You'll see output streaming in real-time as the script runs in an isolated Kubernetes pod (or Docker container in dev mode).

Try modifying the script or switching languages using the dropdown. Each execution gets its own isolated environment with configurable resource limits.

## What's happening under the hood

When you click Run:

1. The frontend sends your script to the backend API
2. Backend validates it, creates an execution record, and publishes an event to Kafka
3. The coordinator worker picks up the event and starts a saga
4. K8s worker spins up an isolated pod with the appropriate runtime
5. Pod monitor watches for completion and captures output
6. Result processor stores the result and publishes it to Redis
7. Your browser receives the result via Server-Sent Events

All of this happens in a few seconds. The event-driven architecture means you can scale each component independently and replay events for debugging.

## Explore the stack

With the stack running, you can poke around:

| Service | URL | What it shows |
|---------|-----|---------------|
| Kafdrop | [http://localhost:9000](http://localhost:9000) | Kafka topics and messages |
| Grafana | [http://localhost:3000](http://localhost:3000) | Metrics dashboards (admin/admin123) |
| Jaeger | [http://localhost:16686](http://localhost:16686) | Distributed traces |

## Troubleshooting

**CPU/memory metrics show as `null`**

The metrics server isn't installed by default in most local Kubernetes setups. Enable it:

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

**Certificate warnings in browser**

Expected - the stack uses self-signed certs for local development. Accept the warning and continue.

**Services failing to start**

Check logs for the specific service: `docker compose logs backend` or `docker compose logs kafka`. Most issues are either port conflicts (something else using 443, 5001, or 9092) or Docker running out of resources.

**Kafka connection errors**

Kafka takes longer to initialize than most services. Give it a minute after `deploy.sh dev` finishes, or watch `docker compose logs kafka` until you see "started" messages.

## Stop the stack

```bash
./deploy.sh down
```

To also remove persistent data (MongoDB, Redis volumes):

```bash
docker compose down -v
```

## Next steps

- [Architecture Overview](architecture/overview.md) - How the pieces fit together
- [Deployment](operations/deployment.md) - Production deployment with Helm
- [API Reference](reference/api-reference.md) - Full endpoint documentation
- [Environment Variables](reference/environment-variables.md) - Configuration options
