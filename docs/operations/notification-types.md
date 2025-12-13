# Notification Model (Unified)

Notifications are producer-driven with minimal core fields. Types and legacy levels have been removed.

Core fields:
- subject: short title
- body: text content
- channel: in_app | webhook | slack
- severity: low | medium | high | urgent
- tags: list of strings, e.g. ['execution','failed'], ['external_alert','grafana']
- status: pending | sending | delivered | failed | skipped | read | clicked

What changed:
- Removed NotificationType, SystemNotificationLevel, templates and rules.
- Producers decide content and tags; UI renders icons/colors from tags+severity.
- Subscriptions filter by severities and include/exclude tags.

Rationale:
- Fewer brittle mappings, simpler flow, better extensibility.

## Tag Conventions

Producers should include small, structured tags to enable filtering, UI actions, and correlation (replacing old related fields):

- Category tags:
  - `execution` — notifications about code executions
  - `external_alert`, `grafana` — notifications from Grafana Alerting

- Entity tags (type):
  - `entity:execution`
  - `entity:external_alert`

- Reference tags (IDs):
  - `exec:<execution_id>` — references a specific execution (used by UI to provide "View result")
  - For external alerts, include any relevant context in `metadata`; tags should avoid unstable IDs unless necessary

- Outcome tags:
  - `completed`, `failed`, `timeout`, `warning`, `error`, `success`

Examples:
- Execution completed: `["execution","completed","entity:execution","exec:2c1b...e8"]`
- Execution failed: `["execution","failed","entity:execution","exec:2c1b...e8"]`
- Grafana alert: `["external_alert","grafana","entity:external_alert"]`
