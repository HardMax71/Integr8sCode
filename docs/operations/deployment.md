# Deployment

Integr8sCode supports two deployment modes: local development using Docker Compose and production deployment to
Kubernetes using Helm. Both modes share the same container images and configuration patterns, so what works locally
translates directly to production.

## Deployment script

The unified `deploy.sh` script in the repository root handles both modes. Running it without arguments shows available
commands.

```bash
./deploy.sh dev              # Start local development stack
./deploy.sh dev --build      # Rebuild images and start
./deploy.sh down             # Stop local stack
./deploy.sh check            # Run quality checks (ruff, mypy, bandit)
./deploy.sh test             # Run full test suite with coverage
./deploy.sh prod             # Deploy to Kubernetes with Helm
./deploy.sh prod --dry-run   # Validate Helm templates without applying
./deploy.sh status           # Show running services
./deploy.sh logs backend     # Tail logs for a specific service
```

The script abstracts away the differences between environments. For local development it orchestrates Docker Compose,
while for production it builds images, imports them to the container runtime, and runs Helm with appropriate values.

## Local development

Local development uses Docker Compose to spin up the entire stack on your machine. The compose file defines all services
with health checks and dependency ordering, so containers start in the correct sequence.

```bash
./deploy.sh dev
```

This brings up MongoDB, Redis, Kafka with Zookeeper and Schema Registry, all seven workers, the backend API, and the
frontend. Two initialization containers run automatically: `kafka-init` creates required Kafka topics, and `user-seed`
populates the database with default user accounts.

Once the stack is running, you can access the services at their default ports.

| Service            | URL                    |
|--------------------|------------------------|
| Frontend           | https://localhost:5001 |
| Backend API        | https://localhost:443  |
| Kafdrop (Kafka UI) | http://localhost:9000  |
| Jaeger (Tracing)   | http://localhost:16686 |
| Grafana            | http://localhost:3000  |

The default credentials created by the seed job are `user` / `user123` for a regular account and `admin` / `admin123`
for an administrator. You can override these via environment variables if needed.

```bash
DEFAULT_USER_PASSWORD=mypass ADMIN_USER_PASSWORD=myadmin ./deploy.sh dev
```

Hot reloading works for the backend since the source directory is mounted into the container. Changes to Python files
trigger Uvicorn to restart automatically. The frontend runs its own dev server with similar behavior.

To stop everything and clean up volumes:

```bash
./deploy.sh down
docker compose down -v  # Also removes persistent volumes
```

### Running tests locally

The `test` command runs the full integration and unit test suite:

```bash
./deploy.sh test
```

This builds images, starts services, waits for the backend health endpoint using curl's built-in retry mechanism, runs
pytest with coverage reporting, then tears down the stack. The curl retry approach is cleaner than shell loops and
avoids issues with Docker Compose's `--wait` flag (which fails on init containers that exit after completion). Key services define healthchecks in `docker-compose.yaml`:

| Service         | Healthcheck                                   |
|-----------------|-----------------------------------------------|
| MongoDB         | `mongosh ping`                                |
| Redis           | `redis-cli ping`                              |
| Backend         | `curl /api/v1/health/live`                    |
| Kafka           | `kafka-broker-api-versions`                   |
| Schema Registry | `curl /config`                                |
| Zookeeper       | `echo ruok \| nc localhost 2181 \| grep imok` |

Services without explicit healthchecks (workers, Grafana, Kafdrop) are considered "started" when their container is
running. The test suite doesn't require worker containers since tests instantiate worker classes directly.

## Kubernetes deployment

Production deployment targets Kubernetes using a Helm chart that packages all manifests and configuration. The chart
lives in `helm/integr8scode/` and includes templates for every component of the stack.

### Prerequisites

Before deploying, ensure you have Helm 3.x installed and kubectl configured to talk to your cluster. If you're using
K3s, the deploy script handles image import automatically. For other distributions, you'll need to push images to a
registry and update the image references in your values file.

### Chart structure

The Helm chart organizes templates by function.

```
helm/integr8scode/
├── Chart.yaml              # Chart metadata and dependencies
├── values.yaml             # Default configuration
├── values-prod.yaml        # Production overrides
├── templates/
│   ├── _helpers.tpl        # Template functions
│   ├── NOTES.txt           # Post-install message
│   ├── namespace.yaml
│   ├── rbac/               # ServiceAccount, Role, RoleBinding
│   ├── secrets/            # Kubeconfig and Kafka JAAS
│   ├── configmaps/         # Environment variables
│   ├── infrastructure/     # Zookeeper, Kafka, Schema Registry, Jaeger
│   ├── app/                # Backend and Frontend deployments
│   ├── workers/            # All seven worker deployments
│   └── jobs/               # Kafka topic init and user seed
└── charts/                 # Downloaded sub-charts (Redis, MongoDB)
```

The chart uses Bitnami sub-charts for Redis and MongoDB since they handle persistence, health checks, and configuration
well. Kafka uses custom templates instead of the Bitnami chart because Confluent images require a specific workaround
for Kubernetes environment variables. Kubernetes automatically creates environment variables like
`KAFKA_PORT=tcp://10.0.0.1:29092` for services, which conflicts with Confluent's expectation of a numeric port. The
templates include an `unset KAFKA_PORT` command in the container startup to avoid this collision.

### Running a deployment

The simplest deployment uses default values, which work for development and testing clusters.

```bash
./deploy.sh prod
```

This builds the Docker images, imports them to K3s (if available), updates Helm dependencies to download the Redis and
MongoDB sub-charts, creates the namespace, and runs `helm upgrade --install`. The `--wait` flag ensures the command
blocks until all pods are ready.

For production environments, pass additional flags to set secure passwords.

```bash
./deploy.sh prod --prod \
    --set userSeed.defaultUserPassword=secure-user-pass \
    --set userSeed.adminUserPassword=secure-admin-pass \
    --set mongodb.auth.rootPassword=mongo-root-pass
```

The `--prod` flag tells the script to use `values-prod.yaml`, which increases replica counts, resource limits, and
enables MongoDB authentication. Without the password flags, the user seed job will fail since the production values
intentionally leave passwords empty to force explicit configuration.

To validate templates without applying anything:

```bash
./deploy.sh prod --dry-run
```

This renders the templates and prints what would be applied, useful for catching configuration errors before they hit
the cluster.

### Configuration

The `values.yaml` file contains all configurable options with comments explaining each setting. Key sections include
global settings, image references, resource limits, and infrastructure configuration.

Environment variables shared across services live in the `env` section and get rendered into a ConfigMap.
Service-specific overrides go in their respective sections. For example, to increase backend replicas and memory:

```yaml
backend:
  replicas: 3
  resources:
    limits:
      memory: "2Gi"
```

Worker configuration follows a similar pattern. Each worker has its own section under `workers` where you can enable or
disable it, set replicas, and override the default command.

```yaml
workers:
  k8sWorker:
    enabled: true
    replicas: 2
  dlqProcessor:
    enabled: false  # Disable if not needed
```

The infrastructure section controls Confluent platform components. You can adjust heap sizes, resource limits, and
enable or disable optional services like Jaeger.

```yaml
infrastructure:
  kafka:
    heapOpts: "-Xms1G -Xmx1G"
    resources:
      limits:
        memory: "2Gi"
  jaeger:
    enabled: false  # Disable tracing in resource-constrained environments
```

### Post-install jobs

Two Helm hooks run after the main deployment completes. The kafka-init job waits for Kafka and Schema Registry to become
healthy, then creates all required topics using the `scripts/create_topics.py` module. Topics are created with the
prefix defined in settings (default `pref`) to avoid conflicts with Kubernetes-generated environment variables.

The user-seed job waits for MongoDB, then runs `scripts/seed_users.py` to create the default and admin users. If users
already exist, the script updates their roles without creating duplicates, making it safe to run on upgrades.

Both jobs have a hook-weight that controls ordering. Kafka init runs first (weight 5), followed by user seed (weight
10). The `before-hook-creation` delete policy ensures old jobs are cleaned up before new ones run, preventing conflicts
from previous releases.

### Accessing deployed services

After deployment, services are only accessible within the cluster by default. Use kubectl port-forward to access them
locally.

```bash
kubectl port-forward -n integr8scode svc/integr8scode-backend 8443:443
kubectl port-forward -n integr8scode svc/integr8scode-frontend 5001:5001
```

For production exposure, enable the ingress section in your values file and configure it for your ingress controller.
The chart supports standard Kubernetes ingress annotations for TLS termination and path routing.

### Monitoring the deployment

Check pod status and logs using standard kubectl commands.

```bash
kubectl get pods -n integr8scode
kubectl logs -n integr8scode -l app.kubernetes.io/component=backend
kubectl logs -n integr8scode -l app.kubernetes.io/component=coordinator
```

The deploy script's `status` command shows both Docker Compose and Kubernetes status in one view.

```bash
./deploy.sh status
```

### Rollback and uninstall

Helm maintains release history, so you can roll back to a previous version if something goes wrong.

```bash
helm rollback integr8scode 1 -n integr8scode
```

To completely remove the deployment:

```bash
helm uninstall integr8scode -n integr8scode
kubectl delete namespace integr8scode
```

This removes all resources created by the chart. Persistent volume claims for MongoDB and Redis may remain depending on
your storage class's reclaim policy.

## Troubleshooting

A few issues come up regularly during deployment.

### Kafka topic errors

If workers log errors about unknown topics, the kafka-init job may have failed or topics were created without the
expected prefix. Check the job logs and verify topics exist with the correct names.

```bash
kubectl logs -n integr8scode job/integr8scode-kafka-init
kubectl exec -n integr8scode integr8scode-kafka-0 -- kafka-topics --list --bootstrap-server localhost:29092
```

Topics should be prefixed (e.g., `prefexecution_events` not `execution_events`). If they're missing the prefix, the
`KAFKA_TOPIC_PREFIX` setting wasn't applied during topic creation.

### Port conflicts with Confluent images

Confluent containers may fail to start with errors about invalid port formats. This happens when Kubernetes environment
variables like `KAFKA_PORT=tcp://...` override the expected numeric values. The chart templates include
`unset KAFKA_PORT` and similar commands, but if you're customizing the deployment, ensure these remain in place.

### Image pull failures

If pods stay in ImagePullBackOff, the images aren't available to the cluster. For K3s, the deploy script imports images
automatically. For other distributions, use the pre-built images from GitHub Container Registry (see below) or push to
your own registry and update `values.yaml` with the correct repository and tag.

```yaml
images:
  backend:
    repository: your-registry.com/integr8scode-backend
    tag: v1.0.0
global:
  imagePullPolicy: Always
```

### MongoDB authentication

When `mongodb.auth.enabled` is true (the default in values-prod.yaml), all connections must authenticate. The chart
constructs the MongoDB URL with credentials from the values file. If you're seeing authentication errors, verify the
password is set correctly and matches what MongoDB was initialized with.

```bash
kubectl get secret -n integr8scode integr8scode-mongodb -o jsonpath='{.data.mongodb-root-password}' | base64 -d
```

### Resource constraints

Workers may get OOMKilled or throttled if resource limits are too low for your workload. The default values are
conservative to work on small clusters. For production, increase limits based on observed usage.

```yaml
workers:
  common:
    resources:
      limits:
        memory: "1Gi"
        cpu: "1000m"
```

Monitor resource usage with kubectl top or your cluster's metrics solution to right-size the limits.

## Pre-built images

For production deployments, you can skip the local build step entirely by using pre-built images from GitHub Container
Registry. The CI pipeline automatically builds and pushes images on every merge to main.

### Using registry images

The `--prod` flag configures the deployment to pull images from `ghcr.io/hardmax71/integr8scode/`:

```bash
./deploy.sh prod --prod \
    --set userSeed.defaultUserPassword=secure-pass \
    --set userSeed.adminUserPassword=secure-admin
```

This skips the local Docker build and tells Kubernetes to pull images from the registry. The `values-prod.yaml` file
sets `imagePullPolicy: IfNotPresent`, so images are cached locally after the first pull.

### Available tags

Each push to main produces multiple tags:

| Tag           | Description                        |
|---------------|------------------------------------|
| `latest`      | Most recent build from main branch |
| `sha-abc1234` | Specific commit SHA                |
| `v1.0.0`      | Release version (from git tags)    |

For production, pin to a specific SHA or version rather than `latest`:

```yaml
images:
  backend:
    repository: ghcr.io/hardmax71/integr8scode/backend
    tag: sha-abc1234
```

### Hybrid approach

If you need production resource limits but want to build locally (for testing changes before pushing):

```bash
./deploy.sh prod --prod --local
```

The `--local` flag forces a local build even when using `values-prod.yaml`.

### CI/CD integration

The GitHub Actions workflow in `.github/workflows/docker.yml` handles image building and publishing. On every push to
main, it builds the base, backend, and frontend images, scans them with Trivy for vulnerabilities, and pushes to
ghcr.io.
Pull requests build and scan but don't push, ensuring only tested code reaches the registry.
