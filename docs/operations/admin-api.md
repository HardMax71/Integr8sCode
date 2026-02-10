# Admin API

The admin API provides endpoints for user management, system settings, and event browsing. All endpoints require
authentication with an admin-role user. The API is organized into three routers: users, settings, and events.

## Authentication

All admin endpoints require the `admin_user` dependency, which validates that the current user has the `admin` role.
Requests from non-admin users receive a 403 Forbidden response.

See [Authentication](../architecture/authentication.md) for details on JWT tokens, CSRF protection, and login flow.

## User Management

The `/api/v1/admin/users` router provides full CRUD operations for user accounts, including listing with
pagination/filtering, creating users, updating profiles, resetting passwords, and managing per-user rate limits.

<swagger-ui src="../reference/openapi.json" filter="users" docExpansion="none" defaultModelsExpandDepth="-1" supportedSubmitMethods="[]"/>

## System Settings

The `/api/v1/admin/settings` router manages global system configuration including execution limits, security settings,
and monitoring parameters.

<swagger-ui src="../reference/openapi.json" filter="settings" docExpansion="none" defaultModelsExpandDepth="-1" supportedSubmitMethods="[]"/>

## Event Management

The `/api/v1/admin/events` router provides event browsing, export, and replay capabilities. Events can be filtered by
type, time range, user, or correlation ID. Results are always sorted by timestamp descending (most recent first).
Export supports CSV and JSON formats.

<swagger-ui src="../reference/openapi.json" filter="admin-events" docExpansion="none" defaultModelsExpandDepth="-1" supportedSubmitMethods="[]"/>

## Key Files

| File                                                                                                                           | Purpose                   |
|--------------------------------------------------------------------------------------------------------------------------------|---------------------------|
| [`api/routes/admin/users.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/api/routes/admin/users.py)       | User management endpoints |
| [`api/routes/admin/settings.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/api/routes/admin/settings.py) | System settings endpoints |
| [`api/routes/admin/events.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/api/routes/admin/events.py)     | Event browsing and replay |
| [`services/admin/`](https://github.com/HardMax71/Integr8sCode/tree/main/backend/app/services/admin)                            | Admin service layer       |
