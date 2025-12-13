# Integr8sCode

**Run Python scripts online in isolated Kubernetes pods with resource limits and real-time feedback.**

Integr8sCode is a platform where you can run Python scripts online with ease. Just paste your script, and the platform runs it in an isolated environment within its own Kubernetes pod, complete with resource limits to keep things safe and efficient. You'll get the results back in no time.

## Quick Start

### Deployment

1. Clone the repository
2. Ensure Docker is enabled, Kubernetes is running, and kubectl is installed
3. Run `docker-compose up --build`

**Access points:**

| Service | URL |
|---------|-----|
| Frontend | `https://127.0.0.1:5001/` |
| Backend API | `https://127.0.0.1:443/` |
| Grafana | `http://127.0.0.1:3000` (admin/admin123) |

### Verify Installation

Check if the backend is running:

```bash
curl -k https://127.0.0.1/api/v1/k8s-limits
```

This should return JSON with current resource limits.

### Enable Kubernetes Metrics

If CPU and Memory metrics show as `null`, enable the metrics server:

```bash
kubectl create -f https://raw.githubusercontent.com/pythianarora/total-practice/master/sample-kubernetes-code/metrics-server.yaml
```

Verify with:

```bash
kubectl top node
```

## Core Features

- **Isolated Execution**: Every script runs in its own Kubernetes pod
- **Resource Limits**: CPU (1000m), Memory (128Mi), configurable timeouts
- **Multi-version Python**: Support for Python 3.10+ and earlier versions
- **Real-time Updates**: Server-Sent Events for live execution status
- **Event Sourcing**: Complete audit trail via Kafka event streams
- **Dead Letter Queue**: Automatic retry and recovery for failed events

## Architecture Overview

The platform is built on three main pillars:

- **Frontend**: Svelte application for user interaction
- **Backend**: FastAPI with MongoDB, Kafka, and Redis
- **Kubernetes**: Isolated pod execution with Cilium network policies

```
User → Frontend → API → Coordinator → Saga → K8s Worker → Pod
                                                  ↓
                              Pod Monitor → Result Processor → SSE → User
```

For detailed architecture diagrams, see the [Architecture](architecture/overview.md) section.

## Security

- **Network Isolation**: Pods cannot make external network calls (Cilium deny-all policy)
- **No Privileged Access**: Pods run as non-root with dropped capabilities
- **Read-only Filesystem**: Containers use read-only root filesystem
- **No Service Account**: Pods have no access to Kubernetes API

## Documentation Sections

<div class="grid cards" markdown>

-   :material-architecture-outline: **[Architecture](architecture/overview.md)**

    ---

    System design, service interactions, and event flows

-   :material-api: **[API Reference](reference/api-reference.md)**

    ---

    Complete REST and SSE endpoint documentation

-   :material-cog: **[Components](components/services-overview.md)**

    ---

    SSE, Workers, DLQ, and Schema management

-   :material-wrench: **[Operations](operations/tracing.md)**

    ---

    Tracing, metrics, monitoring, and troubleshooting

</div>

## Sample Test

Verify your installation by running this Python 3.10+ code:

```python
from typing import TypeGuard

def is_string(value: object) -> TypeGuard[str]:
    return isinstance(value, str)

def example_function(data: object):
    match data:
        case int() if data > 10:
            print("An integer greater than 10")
        case str() if is_string(data):
            print(f"A string: {data}")
        case _:
            print("Something else")

example_function(15)
example_function("hello")
example_function([1, 2, 3])
```

Expected output:

```
An integer greater than 10
A string: hello
Something else
```

## Links

- [GitHub Repository](https://github.com/HardMax71/Integr8sCode)
- [Live Demo](https://app.integr8scode.cc/)
