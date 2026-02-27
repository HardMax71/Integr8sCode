# Frontend Routing

The frontend is a Svelte 5 single-page application using `@mateothegreat/svelte5-router` for client-side routing.
Routes are defined in `App.svelte` with authentication guards for protected pages.

## Route Overview

| Route             | Component              | Auth Required | Admin Required | Description                |
|-------------------|------------------------|---------------|----------------|----------------------------|
| `/`               | `Home.svelte`          | No            | No             | Landing page with features |
| `/login`          | `Login.svelte`         | No            | No             | User login form            |
| `/register`       | `Register.svelte`      | No            | No             | User registration form     |
| `/privacy`        | `Privacy.svelte`       | No            | No             | Privacy policy             |
| `/editor`         | `Editor.svelte`        | Yes           | No             | Code execution interface   |
| `/settings`       | `Settings.svelte`      | Yes           | No             | User preferences           |
| `/notifications`  | `Notifications.svelte` | Yes           | No             | Notification center        |
| `/admin/events`   | `AdminEvents.svelte`   | Yes           | Yes            | Event browser              |
| `/admin/executions` | `AdminExecutions.svelte` | Yes        | Yes            | Execution management       |
| `/admin/sagas`    | `AdminSagas.svelte`    | Yes           | Yes            | Saga monitoring            |
| `/admin/users`    | `AdminUsers.svelte`    | Yes           | Yes            | User management            |
| `/admin/settings` | `AdminSettings.svelte` | Yes           | Yes            | System settings            |

## Route Configuration

Routes are defined in `src/App.svelte` using the router's declarative syntax:

```typescript
--8<-- "frontend/src/App.svelte:routes"
```

## Authentication Guard

The `requireAuth` hook checks the `isAuthenticated` store before allowing navigation:

```typescript
--8<-- "frontend/src/App.svelte:require_auth"
```

When an unauthenticated user tries to access a protected route:

1. The original URL is saved to `sessionStorage`
2. User is redirected to `/login`
3. After successful login, user is redirected back to the original URL

## Admin Role Check

Admin routes perform an additional role check in the component:

```typescript
// In AdminEvents.svelte, AdminUsers.svelte, etc.
import { userRole } from '$stores/auth';
import { get } from 'svelte/store';

if (get(userRole) !== 'ADMIN') {
    goto('/editor');
}
```

## Navigation

### Programmatic Navigation

Use the `goto` function for programmatic navigation:

```typescript
import { goto } from '@mateothegreat/svelte5-router';

// Navigate to editor
goto('/editor');

// Navigate with redirect after login
sessionStorage.setItem('redirectAfterLogin', '/editor');
goto('/login');
```

### Link Navigation

Use the `route` directive for link navigation:

```svelte
<a href="/editor" use:route>Open Editor</a>
<a href="/admin/events" use:route>Event Browser</a>
```

## Route Components

### Public Pages

| Component         | Path                         | Purpose                             |
|-------------------|------------------------------|-------------------------------------|
| `Home.svelte`     | `src/routes/Home.svelte`     | Landing page with features overview |
| `Login.svelte`    | `src/routes/Login.svelte`    | Login form with credential handling |
| `Register.svelte` | `src/routes/Register.svelte` | Registration form with validation   |
| `Privacy.svelte`  | `src/routes/Privacy.svelte`  | Privacy policy content              |

### Protected Pages

| Component              | Path                              | Purpose                          |
|------------------------|-----------------------------------|----------------------------------|
| `Editor.svelte`        | `src/routes/Editor.svelte`        | Code editor with execution       |
| `Settings.svelte`      | `src/routes/Settings.svelte`      | User preferences (theme, editor) |
| `Notifications.svelte` | `src/routes/Notifications.svelte` | Notification list and management |

### Admin Pages

| Component              | Path                                    | Purpose                    |
|------------------------|-----------------------------------------|----------------------------|
| `AdminEvents.svelte`   | `src/routes/admin/AdminEvents.svelte`   | Event browser with filters |
| `AdminExecutions.svelte` | `src/routes/admin/AdminExecutions.svelte` | Execution list and priority management |
| `AdminSagas.svelte`    | `src/routes/admin/AdminSagas.svelte`    | Saga status monitoring     |
| `AdminUsers.svelte`    | `src/routes/admin/AdminUsers.svelte`    | User CRUD and rate limits  |
| `AdminSettings.svelte` | `src/routes/admin/AdminSettings.svelte` | System configuration       |

## State Management

Routes interact with several Svelte stores:

| Store             | Location                      | Purpose                         |
|-------------------|-------------------------------|---------------------------------|
| `isAuthenticated` | `stores/auth.svelte.ts`              | Authentication state            |
| `username`        | `stores/auth.svelte.ts`              | Current username                |
| `userRole`        | `stores/auth.svelte.ts`              | User role (USER/ADMIN)          |
| `csrfToken`       | `stores/auth.svelte.ts`              | CSRF token for API calls        |
| `theme`           | `stores/theme.svelte.ts`             | Current theme (light/dark/auto) |
| `notifications`   | `stores/notificationStore.svelte.ts` | Notification list               |

## SSE Connections

Protected routes may establish SSE connections for real-time updates:

- **Editor**: Connects to `/api/v1/events/executions/{id}` during execution
- **Notifications**: Connects to `/api/v1/events/notifications/stream`

Connections are managed in the component lifecycle:

```typescript
onMount(() => {
    // Establish SSE connection
    const eventSource = new EventSource('/api/v1/events/notifications/stream');
    eventSource.onmessage = (event) => {
        // Handle notification
    };

    return () => {
        eventSource.close();
    };
});
```

## Deep Linking

The router supports deep linking with proper URL handling:

- Direct URL access works for all routes
- 404 handling redirects to home or shows error
- Query parameters are preserved across navigation

## Key Files

| File                                   | Purpose                         |
|----------------------------------------|---------------------------------|
| `src/App.svelte`                       | Route definitions and layout    |
| `src/stores/auth.svelte.ts`                   | Authentication state            |
| `src/lib/auth-init.ts`                 | Auth initialization on app load |
| `src/components/Header.svelte`         | Navigation links                |
| `src/components/ProtectedRoute.svelte` | Route protection wrapper        |
