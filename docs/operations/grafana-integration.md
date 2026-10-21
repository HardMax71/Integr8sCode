# Grafana integration

Grafana runs under the `observability` compose profile. Everything it shows is provisioned from [`backend/grafana/`](https://github.com/HardMax71/Integr8sCode/tree/main/backend/grafana): three datasources, twelve dashboards, two alert rules and an email contact point. Locally it's at `http://localhost:3000`; in production nginx serves it on `grafana.integr8scode.cc` (see [Nginx configuration](nginx-configuration.md#grafana-server)). Anonymous access is off. The admin login comes from `GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD` (default `admin` / `admin123`), and the entrypoint resets the password to that value on every start.

## Datasources

| Name             | Type       | UID                | Notes                                              |
|------------------|------------|--------------------|----------------------------------------------------|
| Victoria Metrics | prometheus | `victoria-metrics` | default; exemplar `trace_id` links to Jaeger       |
| Jaeger           | jaeger     | `jaeger`           | needs Jaeger below 2.21, see [Tracing](tracing.md#jaeger) |
| Loki             | loki       | `loki`             | `trace_id` derived field links to Jaeger          |

Grafana 13 downloads the prometheus and jaeger plugins on first start. `preinstall_sync` in grafana.ini makes it install them before provisioning runs, so the first start on a fresh volume needs to reach grafana.com.

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

## Alerting

[`provisioning/alerting/alerting.yml`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/grafana/provisioning/alerting/alerting.yml) holds the rules, the contact point and the policy:

```yaml
--8<-- "backend/grafana/provisioning/alerting/alerting.yml"
```

Both rules are instant queries on `avg_over_time(system_memory_utilization_ratio{state="used"}[5m]) * 100`, evaluated every minute. One warns above 85% for 5 minutes, the other goes critical above 95% for 2 minutes. The metric comes from the collector's `host_metrics` memory scraper, which emits `system.memory.utilization` only because the collector config turns it on; it's off by default.

Alerts go to the `email-alerts` contact point, which sends one email addressed to everyone in `GRAFANA_ALERT_RECIPIENTS` (`singleEmail: true`). SMTP is configured in grafana.ini from env vars that compose fills in: `GF_SMTP_HOST`, `MAILJET_API_KEY` as the user, `MAILJET_SECRET_KEY` as the password and `MAILJET_FROM_ADDRESS` as the sender. Locally `GF_SMTP_HOST` is empty, so alerts fire but no mail goes out. Production sets it from the `MAILJET_HOST` secret.

The rule group names its folder by title, `Integr8sCode`. If the rules load before the dashboard provider creates that folder, Grafana makes a second `Integr8sCode` folder with a random UID and puts the rules there. The compose entrypoint avoids that: it starts Grafana without the alerting files, waits for `/api/folders/integr8scode`, then copies them in and calls `/api/admin/provisioning/alerting/reload`.

A Grafana volume from before that fix may still have the stray folder holding the rules. Delete it once in the UI (it's the `Integr8sCode` folder whose URL isn't `/dashboards/f/integr8scode/`), then `docker compose restart grafana` so the entrypoint loads the rules into the right one.

## grafana.ini

```ini
--8<-- "backend/grafana/grafana.ini:grafana_ini"
```

`[alerting]` is the legacy engine and stays off. `[unified_alerting]` runs the provisioned rules. There's no `root_url` here; compose sets `GF_SERVER_ROOT_URL` from `GRAFANA_ROOT_URL`.
