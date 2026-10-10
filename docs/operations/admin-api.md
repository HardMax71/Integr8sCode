# Admin API

Five routers under `/api/v1/admin/` make up the admin API. Each one has the `admin_user` dependency at router level, so an anonymous request gets 401 and a logged-in non-admin gets 403. See [Authentication](../architecture/authentication.md) for cookies and CSRF.

| Router        | Prefix                       | What it does                                                                 |
|---------------|------------------------------|------------------------------------------------------------------------------|
| users         | `/admin/users`               | list with search and role filter, create, read, overview, update, delete (cascading by default), reset password, unlock |
| events        | `/admin/events`              | browse, stats, CSV or JSON export, detail, delete, replay, replay status over SSE |
| settings      | `/admin/settings`            | read, replace and reset the system settings (execution limits, login lockout, log level, sampling) |
| executions    | `/admin/executions`          | list executions by status, priority or user, change an execution's priority, queue status |
| rate-limits   | `/admin/rate-limits`         | default rules, and per-user limits: read, update, reset                      |

Per-user rate limits live under `/admin/rate-limits/{user_id}`, not under the users router.

`POST /admin/events/browse` and the export endpoint filter on `event_types`, `aggregate_id`, `user_id`, `service_name` and a `start_time`/`end_time` range. Browse also takes `search_text`. Results come newest first. Export returns up to 10,000 events by default and 50,000 at most.

<swagger-ui src="../reference/openapi.json" filter="admin" docExpansion="none" defaultModelsExpandDepth="-1" supportedSubmitMethods="[]"/>

The handlers are in [`api/routes/admin/`](https://github.com/HardMax71/Integr8sCode/tree/main/backend/app/api/routes/admin) and the services in [`services/admin/`](https://github.com/HardMax71/Integr8sCode/tree/main/backend/app/services/admin).
