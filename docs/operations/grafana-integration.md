# Grafana Integration

The platform accepts Grafana alert webhooks and converts them into in-app notifications. This allows operators to
receive Grafana alerts directly in the application UI without leaving the platform.

## Webhook Endpoint

Configure Grafana to send webhooks to `POST /api/v1/alerts/grafana`. A test endpoint is available to verify connectivity.

<swagger-ui src="../reference/openapi.json" filter="alerts" docExpansion="none" defaultModelsExpandDepth="-1" supportedSubmitMethods="[]"/>

## Webhook Payload

The endpoint expects Grafana's standard webhook format:

```python
--8<-- "backend/app/schemas_pydantic/grafana.py:8:22"
```

Example payload:

```json
{
  "status": "firing",
  "receiver": "integr8scode",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "HighMemoryUsage",
        "severity": "warning",
        "instance": "backend:8000"
      },
      "annotations": {
        "summary": "Memory usage above 80%",
        "description": "Backend instance memory usage is 85%"
      }
    }
  ],
  "commonLabels": {
    "env": "production"
  }
}
```

## Severity Mapping

Grafana severity labels are mapped to notification severity levels:

```python
--8<-- "backend/app/services/grafana_alert_processor.py:14:19"
```

| Grafana Severity | Notification Severity |
|------------------|-----------------------|
| `critical`       | HIGH                  |
| `error`          | HIGH                  |
| `warning`        | MEDIUM                |
| `info`           | LOW                   |

Resolved alerts (status `ok` or `resolved`) are always mapped to LOW severity regardless of the original severity label.

## Processing Flow

The `GrafanaAlertProcessor` processes each alert in the webhook:

1. Extract severity from alert labels or common labels
2. Map severity to notification level
3. Extract title from `alertname` label or `title` annotation
4. Build message from `summary` and `description` annotations
5. Create system notification with metadata

```python
--8<-- "backend/app/services/grafana_alert_processor.py:73:102"
```

## Notification Content

The processor builds notification content as follows:

- **Title**: `labels.alertname` or `annotations.title` or "Grafana Alert"
- **Message**: `annotations.summary` and `annotations.description` joined by newlines
- **Tags**: `["external_alert", "grafana", "entity:external_alert"]`
- **Metadata**: Alert labels, common labels, and status

## Response Format

The endpoint returns processing status:

```json
{
  "message": "Webhook received and processed",
  "alerts_received": 3,
  "alerts_processed": 3,
  "errors": []
}
```

If any alerts fail to process, the error messages are included in the `errors` array but the endpoint still returns 200
for successfully processed alerts.

## Grafana Configuration

To configure Grafana to send alerts:

1. Navigate to **Alerting > Contact points**
2. Create a new contact point with type **Webhook**
3. Set URL to `https://your-domain/api/v1/alerts/grafana`
4. For authenticated environments, configure appropriate headers

The webhook URL should be accessible from your Grafana instance. If using network policies, ensure Grafana can reach the
backend service.

## Key Files

| File                                                                                                                                         | Purpose                 |
|----------------------------------------------------------------------------------------------------------------------------------------------|-------------------------|
| [`services/grafana_alert_processor.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/services/grafana_alert_processor.py) | Alert processing logic  |
| [`api/routes/grafana_alerts.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/api/routes/grafana_alerts.py)               | Webhook endpoint        |
| [`schemas_pydantic/grafana.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/schemas_pydantic/grafana.py)                 | Request/response models |
