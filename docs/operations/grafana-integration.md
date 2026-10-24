# Grafana integration

Everything Grafana shows is provisioned from [`grafana/`](https://github.com/HardMax71/Integr8sCode/tree/main/grafana): three datasources, thirteen dashboards, thirteen alert rules, an email contact point and a heartbeat webhook. Locally it's at `http://localhost:3000`; in production nginx serves it on `grafana.integr8scode.cc` (see [Nginx configuration](nginx-configuration.md#grafana-server)). Anonymous access is off. The admin login comes from `GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD` (default `admin` / `admin123`), and the entrypoint resets the password to that value on every start.

## Datasources

| Name             | Type       | UID                | Notes                                              |
|------------------|------------|--------------------|----------------------------------------------------|
| Victoria Metrics | prometheus | `victoria-metrics` | default; exemplar `trace_id` links to Jaeger       |
| Jaeger           | jaeger     | `jaeger`           | needs Jaeger below 2.21, see [Tracing](tracing.md#jaeger) |
| Loki             | loki       | `loki`             | `trace_id` derived field links to Jaeger          |
| OpenSearch       | grafana-opensearch-datasource | `opensearch` | daily `logs-` indices; `traceId` links to Jaeger, see [OpenSearch](opensearch.md#grafana) |

Grafana 13 downloads the prometheus, jaeger and grafana-opensearch-datasource plugins on first start. `preinstall_sync` in grafana.ini makes it install them before provisioning runs, so the first start on a fresh volume needs to reach grafana.com.

## Dashboards

All dashboards land in one folder, `Integr8sCode`, with the fixed UID `integr8scode`. The file provider reloads them every 10 seconds and doesn't allow saving edits from the UI. The metrics behind them are listed in the [metrics reference](metrics-reference.md).

| File                           | Title                      |
|--------------------------------|----------------------------|
| integr8scode.json            | System Overview            |
| coordinator-execution.json   | Queue & Execution          |
| dlq-monitoring.json          | Dead Letter Queue          |
| event-replay.json            | Event Replay               |
| event-stream-monitoring.json | Event Stream               |
| http-middleware.json         | HTTP & Middleware          |
| kafka-events-monitoring.json | Kafka Events               |
| kubernetes-pods.json         | Kubernetes & Pods          |
| mongodb-monitoring.json      | MongoDB Monitoring         |
| notifications.json           | Notifications              |
| rate-limiting-dashboard.json | Rate Limiting              |
| security-auth.json           | Security & Authentication  |
| errors.json                  | Errors                     |

## Alerting

[`provisioning/alerting/alerting.yml`](https://github.com/HardMax71/Integr8sCode/blob/main/grafana/provisioning/alerting/alerting.yml) holds the rules, the contact point and the policy:

```yaml
--8<-- "grafana/provisioning/alerting/alerting.yml"
```

Every rule is an instant query evaluated every minute, and each summary names the service or mount and the value. Rules that point at a panel carry its `dashboardUid` and `panelId`, and the same two as the `__dashboardUid__` and `__panelId__` annotations, since Grafana puts the panel link into the mail only from those.

| Rule | Fires when | Severity |
|---|---|---|
| Host Memory, Host Disk | memory over 85% for 5 minutes or 95% for 2; disk over 80% for 10 minutes or 90% for 5 | warning, critical |
| Container restarted, Container stopped | Docker restarted a container in the last 10 minutes; a container seen in the last 10 minutes hasn't reported for a minute, for 1 minute | critical |
| Error lines | any error line in 5 minutes, from Loki's `detected_level`; one alert per service and line template ([Loki](loki.md#container-output)), so the mail lists each kind of error with its count | warning |
| API 5xx, Kafka lag, MongoDB down, DLQ | 5xx over 1% for 5 minutes; a group with consumers 100 messages behind for 10 minutes; health under 1 or no data for 2 minutes; any DLQ message for 30 minutes or over 50 for 5 | critical or warning |

The memory and disk rules read the host-metrics collector's scrapers; `system.memory.utilization` is off by default and `otel-host-metrics.yaml` turns it on. The container rules read the collector's docker_stats receiver.

The Heartbeat rule always fires. A child policy sends it to the `heartbeat` contact point, a webhook to `ALERT_HEARTBEAT_URL`, every 5 minutes; the outside monitor behind that URL alerts when the pings stop, since nothing inside the host can report the host's or Grafana's own death. Locally the URL defaults to the collector's health endpoint, which answers any POST.

All other alerts go to the `email-alerts` contact point, which sends one email addressed to everyone in `GRAFANA_ALERT_RECIPIENTS` (`singleEmail: true`). SMTP is configured in grafana.ini from env vars that compose fills in: `GF_SMTP_HOST`, `MAILJET_API_KEY` as the user, `MAILJET_SECRET_KEY` as the password and `MAILJET_FROM_ADDRESS` as the sender. Locally `GF_SMTP_HOST` is empty, so alerts fire but no mail goes out. Production sets it from the `MAILJET_HOST` secret.

The `email` template in the same file writes the subject and the body. The first line is the rule's `description` when it has one, then comes one line per alert from its `summary`, the resolved ones under "Resolved:", and the panel link, or the rule's page for a rule without a panel. An Error lines mail from a local run, with the backend unreachable and the worker failing to create pods, read:

```text
16 errors in the last 5 minutes:
- 1x frontend: 2026/10/24 21:36:35 [error] 41#41: *6 backend could not be resolved (3: Host not found), client: 172.19.0.1, server: _, request: "GET /api/v1/x1 HTTP/1.1", host: "localhost:15001"
- 10x frontend: 2026/10/24 <*> [error] <*> <*> backend could not be resolved (3: Host not found), client: 172.19.0.1, server: _, request: "GET <*> HTTP/1.1", host: "localhost:15001"
- 1x integr8scode-worker: {"event": "Pod creation failed", "execution_id": "a1b2", "error": "boom", "logger": "integr8scode", "level": "error", "timestamp": "2026-10-24T21:30:00.000Z", <exception>}
- 4x integr8scode-worker: {"event": "Pod creation failed", "execution_id": <*> "error": <*> "logger": "integr8scode", "level": "error", "timestamp": <*> <exception>}

https://grafana.integr8scode.cc/d/errors?orgId=1&viewPanel=5
```

The 1x lines are the first of each shape: the collector keeps a line whole until a second one like it arrives.

The rule group names its folder by title, `Integr8sCode`. If the rules load before the dashboard provider creates that folder, Grafana makes a second `Integr8sCode` folder with a random UID and puts the rules there. The compose entrypoint avoids that: it starts Grafana without the alerting files, waits for `/api/folders/integr8scode`, then copies them in and calls `/api/admin/provisioning/alerting/reload`.

A Grafana volume from before that fix may still have the stray folder holding the rules. Delete it once in the UI (it's the `Integr8sCode` folder whose URL isn't `/dashboards/f/integr8scode/`), then `docker compose restart grafana` so the entrypoint loads the rules into the right one.

## grafana.ini

```ini
--8<-- "grafana/grafana.ini:grafana_ini"
```

`[alerting]` is the legacy engine and stays off. `[unified_alerting]` runs the provisioned rules. There's no `root_url` here; compose sets `GF_SERVER_ROOT_URL` from `GRAFANA_ROOT_URL`.
