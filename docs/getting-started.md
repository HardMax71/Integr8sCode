# Getting started

You need Docker with Compose and a Kubernetes cluster that kubectl on your machine can reach. Docker alone isn't enough: every script runs in a Kubernetes pod, and there's no Docker fallback. The project runs on k3s, locally and in CI.

## Set up k3s

If you don't have a cluster yet, install k3s with these flags, so containers can reach its API at `host.docker.internal` with a valid certificate:

```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable=traefik --bind-address 0.0.0.0 --tls-san host.docker.internal" sh -
```

CI also passes `--disable-network-policy` to dodge the iptables race under [Troubleshooting](#troubleshooting). Leave it out here: without the policy controller, k3s doesn't enforce the NetworkPolicy that cuts executor pods off the network.

On startup the `cert-generator` container looks for the cluster through `~/.kube` and `/etc/rancher/k3s`. When it finds one, it creates the `integr8scode` namespace, installs Kueue, sets up a service account and writes `backend/kubeconfig.yaml` for the workers. When it can't connect, it logs "Cannot connect to Kubernetes cluster" and skips all of that. The rest of the stack still starts and you can log in, but the worker has no kubeconfig and keeps restarting, so scripts stay queued forever.

## Start the stack

```bash
git clone https://github.com/HardMax71/Integr8sCode.git
cd Integr8sCode
./deploy.sh dev
```

The first start pulls or builds the images and takes a few minutes. Secrets (JWT key, MongoDB and Redis passwords) come from environment variables with dev defaults, so there's nothing to copy or fill in. Add `--wait` to block until every service is running, and healthy where it has a healthcheck.

Check the backend:

```bash
curl -k https://localhost/api/v1/health/live
```

```json
{"status":"ok","uptime_seconds":42,"timestamp":"2026-01-25T12:00:00Z"}
```

## Log in and run a script

Open [https://localhost:5001](https://localhost:5001) and accept the self-signed certificate. Log in with username `user` and password `user123`. For the admin pages (events, executions, sagas, users, system settings) use `admin` / `admin123`. A one-shot `user-seed` container creates both accounts, or resets their passwords, on every start. Set `DEFAULT_USER_PASSWORD` and `ADMIN_USER_PASSWORD` before deploying anywhere that isn't your laptop.

After login you land in the editor, which starts with a small Python script. Click **Run Script** and the editor shows the status while the pod runs, then the output once it finishes. The language picker offers what the runtime registry lists: Python 3.14, 3.13, 3.12 and 3.11, Node 26, 24 and 22, Ruby 4.0, 3.4 and 3.3, Go 1.27 and 1.26, and Bash 5.3.

Limits are system-wide, not per execution. An execution request carries only the script, `lang` and `lang_version`. CPU, memory and timeout are admin system settings, seeded on first start from config.toml: 1000m CPU, 128Mi memory and a 5 second timeout. Admins change them at `/admin/settings`. A language can raise them for its own pods. Go gets at least 30 seconds, 1000m CPU, 320Mi memory and 64Mi of `/tmp`, since a cold `go run` compiles the standard library first.

## What happens when you click Run

1. The frontend posts the script, language and version to `POST /api/v1/execute`.
2. The API checks the version is offered, writes an execution document and publishes `execution_requested` to Kafka.
3. The saga orchestrator puts the execution in a Redis priority queue. When fewer than 10 executions are active (an admin setting), it runs the saga, which publishes `create_pod_command`.
4. The k8s worker creates a ConfigMap with the script and a locked-down pod.
5. The pod monitor sees the pod finish, reads its output and publishes `execution_completed`, `execution_failed` or `execution_timeout`, then deletes the pod.
6. The result processor writes the result onto the execution document and publishes `result_stored`.
7. The API forwards these events from Kafka through Redis to your browser over Server-Sent Events.

[Workers](components/workers/index.md) and [Execution SSE flow](components/sse/execution-sse-flow.md) go through each step.

## Look around

Kafdrop, Grafana and Jaeger aren't part of the default stack. `./deploy.sh dev --observability` adds Grafana, Jaeger, Victoria Metrics, Loki and the OTel collector, and `--debug` adds Kafdrop on top. All of them listen on localhost only.

| Service | URL | Needs |
|---------|-----|-------|
| Grafana | [http://localhost:3000](http://localhost:3000) (admin / admin123) | `--observability` or `--debug` |
| Jaeger | [http://localhost:16686](http://localhost:16686) | `--observability` or `--debug` |
| Kafdrop | [http://localhost:9000](http://localhost:9000) | `--debug` |

## Troubleshooting

If scripts stay queued, check `docker compose logs cert-generator` for the connection error above, then `docker compose logs worker`. A k3s that stopped after a VPN or IP change is covered in [Deployment](operations/deployment.md).

If every service times out talking to mongo or kafka right after k3s started or restarted, k3s's policy sync probably wiped Docker's iptables rules ([kube-router#1248](https://github.com/cloudnativelabs/kube-router/issues/1248)). `docker compose down` followed by `./deploy.sh dev` recreates the network and its rules.

If a service fails to start, `docker compose logs <service>` usually says why. The usual causes are a port already in use (443, 5001, or 27017, 6379 and 9092 on localhost) or Docker running out of memory.

## Stop the stack

```bash
./deploy.sh down
```

To delete the MongoDB, Redis and Kafka data as well:

```bash
docker compose down -v
```

[Configuration](reference/configuration.md) lists every setting, and the [API reference](reference/api-reference.md) has every endpoint.
