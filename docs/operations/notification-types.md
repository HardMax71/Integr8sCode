# Notifications

Notifications are producer-driven with minimal core fields. Types and legacy levels have been removed.

## Core fields

- `subject`: short title
- `body`: text content
- `channel`: in_app | webhook | slack
- `severity`: low | medium | high | urgent
- `tags`: list of strings, e.g. `['execution','failed']`, `['external_alert','grafana']`
- `status`: pending | sending | delivered | failed | skipped | read | clicked

## Tag conventions

Producers should include small, structured tags to enable filtering, UI actions, and correlation (replacing old related fields).

**Category tags** indicate what the notification is about: `execution` for code executions, `external_alert` and `grafana` for notifications from Grafana Alerting.

**Entity tags** specify the type: `entity:execution`, `entity:external_alert`.

**Reference tags** link to specific resources: `exec:<execution_id>` references a specific execution (used by UI to provide "View result"). For external alerts, include relevant context in `metadata` rather than unstable IDs in tags.

**Outcome tags** describe what happened: `completed`, `failed`, `timeout`, `warning`, `error`, `success`.

## Examples

Execution completed:
```json
["execution", "completed", "entity:execution", "exec:2c1b...e8"]
```

Execution failed:
```json
["execution", "failed", "entity:execution", "exec:2c1b...e8"]
```

Grafana alert:
```json
["external_alert", "grafana", "entity:external_alert"]
```
