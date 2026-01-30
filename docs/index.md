<div style="text-align: center;" markdown>

![Integr8sCode](assets/images/logo.png){ width="150" }

# Integr8sCode

[GitHub :material-github:](https://github.com/HardMax71/Integr8sCode){ .md-button }
[Live Demo :material-play:](https://app.integr8scode.cc/){ .md-button .md-button--primary }

Run Python scripts in isolated Kubernetes pods with real-time output streaming, resource limits, and full audit trails.

</div>

## Quick start

```bash
git clone https://github.com/HardMax71/Integr8sCode.git
cd Integr8sCode
./deploy.sh dev
```

Then open [https://localhost:5001](https://localhost:5001) and log in with `user` / `user123`.

For the full walkthrough, see [Getting Started](getting-started.md).

## Core features

Every script runs in its own Kubernetes pod with complete isolation. Resource limits are configurable per execution
(defaults: 1000m CPU, 128Mi memory, 300s timeout).

The platform supports multiple languages and versions:

| Language | Versions                       |
|----------|--------------------------------|
| Python   | 3.7, 3.8, 3.9, 3.10, 3.11, 3.12|
| Node.js  | 18, 20, 22                     |
| Ruby     | 3.1, 3.2, 3.3                  |
| Go       | 1.20, 1.21, 1.22               |
| Bash     | 5.1, 5.2, 5.3                  |

Execution output streams in real-time via Server-Sent Events. All events flow through Kafka for full audit trails, with
automatic retries via dead letter queue for failed processing.

## Documentation

<div class="grid cards" markdown>

-   :material-rocket-launch: **[Getting Started](getting-started.md)**

    ---

    Run the stack locally and execute your first script

-   :material-sitemap: **[Architecture](architecture/overview.md)**

    ---

    System design, service interactions, and event flows

-   :material-api: **[API Reference](reference/api-reference.md)**

    ---

    Complete REST and SSE endpoint documentation

-   :material-cog: **[Components](components/workers/index.md)**

    ---

    Workers, SSE, DLQ, and Schema management

-   :material-wrench: **[Operations](operations/deployment.md)**

    ---

    Deployment, tracing, and monitoring

-   :material-shield: **[Security](SECURITY.md)**

    ---

    Policies, network isolation, and supply chain

-   :material-cog: **[Configuration Reference](reference/configuration.md)**

    ---

    TOML configuration and secrets

-   :material-monitor: **[Frontend](frontend/routing.md)**

    ---

    Frontend routing and components

-   :material-github: **[Contributing](https://github.com/HardMax71/Integr8sCode/blob/main/CONTRIBUTING.md)**

    ---

    Development setup, pre-commit hooks, and PR guidelines

</div>
