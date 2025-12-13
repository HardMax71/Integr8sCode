# API Reference: All Endpoints

Base URL and version
- Base URL: https://localhost:443
- API prefix: /api/v1
- Auth: Cookie `access_token` (httpOnly) after login. For state‑changing requests (POST/PUT/DELETE), include header `X-CSRF-Token` with the `csrf_token` cookie value.

Conventions
- All curl examples use `-k` for local HTTPS and `-b cookies.txt`/`-c cookies.txt` to read/write cookies.
- Timestamps are ISO 8601 unless noted.

Authentication (/auth)
- POST /auth/register
  - Body: { username, email, password }
  - 201: UserResponse
  - Example: curl -k -X POST https://localhost:443/api/v1/auth/register -H 'Content-Type: application/json' -d '{"username":"alice","email":"a@example.com","password":"s3cr3t"}'

- POST /auth/login
  - Form: username, password (x-www-form-urlencoded)
  - Sets cookies: access_token (httpOnly), csrf_token
  - 200: { message, username, role, csrf_token }
  - Example: curl -k -X POST https://localhost:443/api/v1/auth/login -H 'Content-Type: application/x-www-form-urlencoded' -d 'username=alice&password=s3cr3t' -c cookies.txt

- GET /auth/me
  - Auth: cookie
  - 200: UserResponse
  - Example: curl -k https://localhost:443/api/v1/auth/me -b cookies.txt

- GET /auth/verify-token
  - Auth: cookie
  - 200: { valid, username, role, csrf_token }
  - Example: curl -k https://localhost:443/api/v1/auth/verify-token -b cookies.txt

- POST /auth/logout
  - Clears auth and CSRF cookies
  - Example: curl -k -X POST https://localhost:443/api/v1/auth/logout -b cookies.txt -c cookies.txt

Executions and Results
- POST /execute
  - Auth: cookie, Header: X-CSRF-Token
  - Body: { script, lang, lang_version }
  - Optional: Idempotency-Key header
  - 200: { execution_id, status }
  - Example: curl -k -X POST https://localhost:443/api/v1/execute -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" -b cookies.txt -d '{"script":"print(1)","lang":"python","lang_version":"3.11"}'

- GET /result/{execution_id}
  - 200: ExecutionResult (output, errors, status, exit_code, resource_usage)
  - Example: curl -k https://localhost:443/api/v1/result/<id> -b cookies.txt

- POST /{execution_id}/cancel
  - Auth: cookie, X-CSRF-Token
  - Body: { reason? }
  - 200: CancelResponse
  - Example: curl -k -X POST https://localhost:443/api/v1/<id>/cancel -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" -b cookies.txt -d '{"reason":"user"}'

- POST /{execution_id}/retry
  - Auth: cookie, X-CSRF-Token
  - 200: ExecutionResponse (new execution)
  - Example: curl -k -X POST https://localhost:443/api/v1/<id>/retry -H "X-CSRF-Token: $CSRF" -b cookies.txt -d '{}'

- GET /executions/{execution_id}/events
  - Query: event_types (csv), limit
  - 200: [ExecutionEventResponse]
  - Example: curl -k 'https://localhost:443/api/v1/executions/<id>/events?event_types=execution_failed&limit=50' -b cookies.txt

- GET /user/executions
  - Query: status, lang, start_time, end_time, limit, skip
  - 200: ExecutionListResponse

- GET /example-scripts; GET /k8s-limits
  - 200: ExampleScripts / ResourceLimits

- DELETE /{execution_id} (admin)
  - 200: DeleteResponse

SSE Streams (/events via sse router)
- GET /events/executions/{execution_id}
  - Streams execution events. Terminal is `result_stored` with final payload; stream closes.
  - Example: curl -k -N https://localhost:443/api/v1/events/executions/<id> -b cookies.txt

- GET /events/notifications/stream
  - User‑specific notifications stream.

- GET /events/health
  - SSE service health summary.

Events (query, stats, publish)
- GET /events/executions/{execution_id}/events
  - Persisted events for an execution; `include_system_events=true` to include internal.

- GET /events/user
  - Query: event_types[], start_time, end_time, limit, skip, sort_order
  - 200: EventListResponse

- POST /events/query
  - Body: EventFilterRequest
  - 200: EventListResponse

- GET /events/correlation/{correlation_id}
  - 200: EventListResponse

- GET /events/current-request
  - 200: EventListResponse (events associated with the current HTTP request)

- GET /events/statistics
  - Query: start_time, end_time, include_all_users
  - 200: EventStatistics

- GET /events/{event_id}
  - 200: EventResponse

- POST /events/publish (admin)
  - Body: PublishEventRequest (typed payload)
  - 200: PublishEventResponse

- POST /events/aggregate (admin)
  - Body: EventAggregationRequest (pipeline, limit)
  - 200: list[dict]

- GET /events/types
  - 200: [event_type]

- DELETE /events/{event_id} (admin)
  - 200: DeleteEventResponse

- POST /events/replay/{aggregate_id} (admin)
  - Query: target_service?, dry_run=true|false
  - 200: ReplayAggregateResponse

Saved Scripts (/scripts)
- POST /scripts; GET /scripts; GET /scripts/{id}; PUT /scripts/{id}; DELETE /scripts/{id}
  - Auth: cookie; send X-CSRF-Token for write ops
  - 200/204 with SavedScriptResponse or empty body

User Settings (/user/settings)
- GET /user/settings/
- PUT /user/settings/
- PUT /user/settings/theme
- PUT /user/settings/notifications
- PUT /user/settings/editor
- GET /user/settings/history
- POST /user/settings/restore
- PUT /user/settings/custom/{key}
  - Auth: cookie; X-CSRF-Token for write ops

Notifications (/notifications)
- GET /notifications (status?, limit, offset)
- PUT /notifications/{notification_id}/read (204)
- POST /notifications/mark-all-read (204)
- GET /notifications/subscriptions
- PUT /notifications/subscriptions/{channel}
- GET /notifications/unread-count
- DELETE /notifications/{notification_id}
  - Auth: cookie; X-CSRF-Token for write ops

Notification Model
- Fields: `channel`, `severity` (low|medium|high|urgent), `subject`, `body`, `tags: string[]`, `status`.
- Producers choose tags; UI/icons derive from `tags` + `severity`. No NotificationType/levels.

Sagas (/sagas)
- GET /sagas/{saga_id}
- GET /sagas/execution/{execution_id}
- GET /sagas?state=&limit=&offset=
- POST /sagas/{saga_id}/cancel
  - Auth: cookie; X-CSRF-Token for cancel

Admin: Events (/admin/events)
- POST /admin/events/browse
- GET /admin/events/stats?hours=24
- GET /admin/events/{event_id}
- POST /admin/events/replay (dry_run|target)| returns session info
- GET /admin/events/replay/{session_id}/status
- DELETE /admin/events/{event_id}
- GET /admin/events/export/csv (filters via query)
- GET /admin/events/export/json (filters via query)
  - Auth: admin cookie; X-CSRF-Token for deletes

Admin: Settings (/admin/settings)
- GET /admin/settings/
- PUT /admin/settings/
- POST /admin/settings/reset
  - Auth: admin; X-CSRF-Token for write ops

Admin: Users (/admin/users)
- GET /admin/users?limit=&offset=&search=&role=
- POST /admin/users
- GET /admin/users/{user_id}
- GET /admin/users/{user_id}/overview
- PUT /admin/users/{user_id}
  - Auth: admin; X-CSRF-Token for write ops

DLQ (/dlq)
- GET /dlq/stats
- GET /dlq/messages?status=&topic=&event_type=&limit=&offset=
- GET /dlq/messages/{event_id}
- POST /dlq/retry (ManualRetryRequest)
- POST /dlq/retry-policy (topic, strategy, limits)
- DELETE /dlq/messages/{event_id}?reason=
- GET /dlq/topics
  - Auth: cookie; X-CSRF-Token for write ops

Replay (/replay) [admin]
- POST /replay/sessions (ReplayRequest)
- POST /replay/sessions/{session_id}/start
- POST /replay/sessions/{session_id}/pause
- POST /replay/sessions/{session_id}/resume
- POST /replay/sessions/{session_id}/cancel
- GET /replay/sessions?status=&limit=
- GET /replay/sessions/{session_id}
- POST /replay/cleanup?older_than_hours=24

Grafana Alerting (/alerts)
- POST /alerts/grafana
  - Body: GrafanaWebhook (minimal Grafana schema)
  - 200: { message, alerts_received, alerts_processed, errors[] }
  - Processes alerts into notifications; no auth (designed for internal webhook).
  
  Grafana configuration notes:
  - Create a contact point of type "Webhook" with URL: `https://<your-host>/api/v1/alerts/grafana`.
  - Optional HTTP method: POST (default). No auth headers required by default.
  - Map severity: set label `severity` on your alert rules (e.g., critical|error|warning). The backend maps:
    - critical|error → severity=high
    - resolved/ok status → severity=low
    - otherwise → severity=medium
  - Tags are set to `["external_alert","grafana"]` in notifications; add more via labels if desired.
  - The title is taken from `labels.alertname` or `annotations.title`; the body is built from `annotations.summary` and `annotations.description`.

- GET /alerts/grafana/test
  - Returns static readiness info.

Health (no prefix)
- GET /health/healthz → liveness: { status: "alive" }
- GET /health/readyz → readiness with dependency checks (Mongo, Kafka, Event Store, K8s)
- GET /health/health → simple status summary

Rate limiting

Every request passes through the rate limiter before reaching the handler. The limiter resolves the caller's identity (user_id for authenticated requests, IP address for anonymous) and checks against Redis using a sliding window algorithm. Anonymous users get a 0.5x multiplier on limits compared to authenticated users.

When a request is allowed, the response includes `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` headers so clients can track their quota. When denied, the API returns 429 with the same headers plus `Retry-After`. Admins can configure per-user limits through the admin UI and view usage stats.

Notes on security
- Auth required for most endpoints; admin‑only routes enforce role checks server‑side.
- CSRF double‑submit cookie pattern is enforced for state‑changing routes.
- SSE endpoints require auth cookie; they stream only data for the current user (or a specific execution the user owns).
