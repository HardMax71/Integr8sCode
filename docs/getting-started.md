# Getting started

You need Docker with Compose and k3s on the same machine. Docker alone isn't enough: every script runs in a Kubernetes pod, and there's no Docker fallback. The project runs on k3s, locally and in CI.

## Set up k3s

If you don't have a cluster yet, install k3s with these flags, so containers can reach its API at `host.docker.internal` with a valid certificate:

```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable=traefik --bind-address 0.0.0.0 --tls-san host.docker.internal" sh -
```

CI also passes `--disable-network-policy` to dodge the iptables race under [Troubleshooting](#troubleshooting). Leave it out here: without the policy controller, k3s doesn't enforce the NetworkPolicy that cuts executor pods off the network.

That's all the cluster needs. The worker reads k3s's own kubeconfig from `/etc/rancher/k3s/k3s.yaml`, talks to `https://host.docker.internal:6443` (the name the `--tls-san` flag puts on k3s's certificate) and on start creates the `integr8scode` namespace with its Pod Security labels, NetworkPolicy and ResourceQuota.

## Start the stack

```bash
git clone https://github.com/HardMax71/Integr8sCode.git
cd Integr8sCode
cp .env.example .env
docker compose up -d
```

The first start pulls or builds the images and takes a few minutes. `.env` holds the local secrets (JWT key, MongoDB and Redis passwords, the two logins), and `.env.example` has working values, so there's nothing to fill in. Add `--wait` to block until every service is running, and healthy where it has a healthcheck.

Check the backend:

```bash
curl -k https://localhost:5001/api/v1/health/live
```

```json
{"status":"ok","uptime_seconds":42,"timestamp":"2026-01-25T12:00:00Z"}
```

## Log in and run a script

Open [https://localhost:5001](https://localhost:5001) and accept the self-signed certificate. Log in with username `user` and password `user123`. For the admin pages (events, executions, users, system settings) use `admin` / `admin123`. The backend creates both accounts, or resets their passwords, every time it starts. Anywhere that isn't your laptop, put your own values in `.env`.

After login you land in the editor, which starts with a small Python script. Click **Run Script** and the editor shows the status while the pod runs, then the output once it finishes. The language picker offers what the runtime registry lists: Python 3.14, 3.13, 3.12 and 3.11, Node 26, 24 and 22, Ruby 4.0, 3.4 and 3.3, Go 1.27 and 1.26, and Bash 5.3.

Limits are system-wide, not per execution. An execution request carries only the script, `lang` and `lang_version`. CPU, memory and timeout are admin system settings, seeded on first start from config.toml: 1000m CPU, 128Mi memory and a 5 second timeout. Admins change them at `/admin/settings`. A language can raise them for its own pods. Go gets at least 30 seconds, 1000m CPU, 320Mi memory and 64Mi of `/tmp`, since a cold `go run` compiles the standard library first.

## What happens when you click Run

1. The frontend posts the script, language and version to `POST /api/v1/execute`.
2. The API checks the version is offered, writes an execution document and publishes `execution_requested` to Kafka.
3. The worker's execution scheduler puts the execution in a Redis priority queue. When fewer than 10 executions are active (an admin setting), it starts it.
4. The k8s worker creates a ConfigMap with the script and a locked-down pod.
5. The pod monitor sees the pod finish, reads its output and hands it to the result processor, then deletes the pod and frees the slot.
6. The result processor writes the result onto the execution document and publishes `execution_completed`, `execution_failed` or `execution_timeout`, then `result_stored`.
7. The API forwards these events from Kafka through Redis to your browser over Server-Sent Events.

[Workers](components/workers/index.md) and [Execution SSE flow](components/sse/execution-sse-flow.md) go through each step.

## Look around

Kafdrop, Grafana and Jaeger aren't part of the default stack. `docker compose --profile observability up -d` adds Grafana, Jaeger, Victoria Metrics, Loki, OpenSearch and the OTel collector, and `--profile debug` adds Kafdrop. All of them listen on localhost only.

| Service | URL | Needs |
|---------|-----|-------|
| Grafana | [http://localhost:3000](http://localhost:3000) (admin / admin123) | `--profile observability` |
| Jaeger | [http://localhost:16686](http://localhost:16686) | `--profile observability` |
| Kafdrop | [http://localhost:9000](http://localhost:9000) | `--profile debug` |

## Troubleshooting

If scripts stay queued, check `docker compose logs worker`, which logs the Kubernetes error when it can't reach k3s. A k3s that stopped after a VPN or IP change is covered in [Deployment](operations/deployment.md).

If every service times out talking to mongo or kafka right after k3s started or restarted, k3s's policy sync probably wiped Docker's iptables rules ([kube-router#1248](https://github.com/cloudnativelabs/kube-router/issues/1248)). `docker compose down` followed by `docker compose up -d` recreates the network and its rules.

If a service fails to start, `docker compose logs <service>` usually says why. The usual causes are a port already in use (443, 5001, or 27017, 6379 and 9092 on localhost) or Docker running out of memory.

## Stop the stack

```bash
docker compose down
```

To delete the MongoDB, Redis and Kafka data as well:

```bash
docker compose down -v
```

[Configuration](reference/configuration.md) lists every setting, and the [API reference](reference/api-reference.md) has every endpoint.
