# API Reference

The API is served at `/api/v1/` and uses cookie-based JWT authentication with CSRF protection.

## Quick Reference

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/login` | Login with username/password |
| POST | `/auth/register` | Register new user |
| POST | `/auth/logout` | Logout and clear cookies |
| GET | `/auth/verify-token` | Verify current token |
| GET | `/auth/me` | Get current user profile |

### Execution

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/execute` | Execute a script |
| GET | `/result/{execution_id}` | Get execution result |
| POST | `/{execution_id}/cancel` | Cancel running execution |
| POST | `/{execution_id}/retry` | Retry execution |
| DELETE | `/{execution_id}` | Delete execution (admin) |
| GET | `/user/executions` | List user's executions |
| GET | `/executions/{execution_id}/events` | Get execution events |
| GET | `/k8s-limits` | Get resource limits and runtimes |
| GET | `/example-scripts` | Get example scripts |

### Events & SSE

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/events/executions/{execution_id}` | SSE stream for execution |
| GET | `/events/notifications/stream` | SSE stream for notifications |
| GET | `/events/health` | SSE service health |
| GET | `/events/user` | Get user's events |
| GET | `/events/{event_id}` | Get specific event |
| POST | `/events/query` | Query events with filters |
| GET | `/events/correlation/{correlation_id}` | Get events by correlation ID |
| GET | `/events/statistics` | Event statistics |
| GET | `/events/types/list` | List event types |

### Saved Scripts

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/scripts` | List saved scripts |
| POST | `/scripts` | Create saved script |
| GET | `/scripts/{script_id}` | Get saved script |
| PUT | `/scripts/{script_id}` | Update saved script |
| DELETE | `/scripts/{script_id}` | Delete saved script |

### Notifications

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/notifications` | List notifications |
| PUT | `/notifications/{id}/read` | Mark as read |
| POST | `/notifications/mark-all-read` | Mark all as read |
| DELETE | `/notifications/{id}` | Delete notification |
| GET | `/notifications/subscriptions` | Get subscriptions |
| PUT | `/notifications/subscriptions/{channel}` | Update subscription |
| GET | `/notifications/unread-count` | Get unread count |

### Sagas

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/sagas/` | List sagas |
| GET | `/sagas/{saga_id}` | Get saga status |
| GET | `/sagas/execution/{execution_id}` | Get sagas for execution |
| POST | `/sagas/{saga_id}/cancel` | Cancel saga |

### User Settings

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/user-settings` | Get user settings |
| PUT | `/user-settings` | Update user settings |
| PUT | `/user-settings/theme` | Update theme |
| PUT | `/user-settings/editor` | Update editor settings |

### Replay

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/replay/sessions` | Create replay session |
| POST | `/replay/sessions/{id}/start` | Start session |
| POST | `/replay/sessions/{id}/pause` | Pause session |
| POST | `/replay/sessions/{id}/resume` | Resume session |
| POST | `/replay/sessions/{id}/cancel` | Cancel session |
| GET | `/replay/sessions` | List sessions |
| GET | `/replay/sessions/{id}` | Get session details |
| POST | `/replay/cleanup` | Clean up old sessions |

### Dead Letter Queue

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/dlq/stats` | DLQ statistics |
| GET | `/dlq/messages` | List DLQ messages |
| GET | `/dlq/messages/{event_id}` | Get DLQ message |
| POST | `/dlq/retry` | Retry messages |
| POST | `/dlq/retry-policy` | Set retry policy |
| DELETE | `/dlq/messages/{event_id}` | Discard message |
| GET | `/dlq/topics` | Get topics summary |

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health/live` | Liveness probe |
| GET | `/health/ready` | Readiness probe |

### Admin - Users

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/users/` | List all users |
| POST | `/admin/users/` | Create user |
| GET | `/admin/users/{user_id}` | Get user details |
| GET | `/admin/users/{user_id}/overview` | Get user overview |
| PUT | `/admin/users/{user_id}` | Update user |
| DELETE | `/admin/users/{user_id}` | Delete user |
| POST | `/admin/users/{user_id}/reset-password` | Reset password |
| GET | `/admin/users/{user_id}/rate-limits` | Get rate limits |
| PUT | `/admin/users/{user_id}/rate-limits` | Update rate limits |
| POST | `/admin/users/{user_id}/rate-limits/reset` | Reset rate limits |

### Admin - Settings

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/settings/` | Get system settings |
| PUT | `/admin/settings/` | Update settings |
| POST | `/admin/settings/reset` | Reset to defaults |

### Admin - Events

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/admin/events/browse` | Browse events |
| GET | `/admin/events/stats` | Event statistics |
| GET | `/admin/events/{event_id}` | Get event detail |
| DELETE | `/admin/events/{event_id}` | Delete event |
| POST | `/admin/events/replay` | Replay events |
| GET | `/admin/events/replay/{id}/status` | Get replay status |
| GET | `/admin/events/export/csv` | Export as CSV |
| GET | `/admin/events/export/json` | Export as JSON |

### Grafana Alerts

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/alerts/grafana` | Receive Grafana webhook |
| GET | `/alerts/grafana/test` | Test endpoint |

---

## Interactive Documentation

<swagger-ui src="openapi.json" deepLinking="true" docExpansion="list" supportedSubmitMethods="[]"/>
