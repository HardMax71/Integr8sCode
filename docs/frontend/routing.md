# Frontend routing

The frontend is a Svelte 5 single-page app routed by `@mateothegreat/svelte5-router`. All routes are one array in `src/App.svelte`. Protected routes share a `requireAuth` pre-hook, and admin routes use `requireAdmin`, which also checks the role.

## Routes

```typescript
--8<-- "frontend/src/App.svelte:routes"
```

Every page component is lazy-loaded with an `async () => import(...)` wrapper, so each page is its own chunk. The wrappers have to be `async` functions, because the router recognises lazy components by `constructor.name === "AsyncFunction"`. `/admin` on its own is a regex route that shows the event browser.

| Path                 | Component                | Guard            |
|----------------------|--------------------------|------------------|
| `/`                  | Home.svelte            | none             |
| `/login`             | Login.svelte           | none             |
| `/register`          | Register.svelte        | none             |
| `/privacy`           | Privacy.svelte         | none             |
| `/editor`            | Editor.svelte          | login            |
| `/settings`          | Settings.svelte        | login            |
| `/notifications`     | Notifications.svelte   | login            |
| `/admin`, `/admin/events` | `admin/AdminEvents.svelte` | login, admin |
| `/admin/executions`  | `admin/AdminExecutions.svelte` | login, admin |
| `/admin/sagas`       | `admin/AdminSagas.svelte` | login, admin    |
| `/admin/users`       | `admin/AdminUsers.svelte` | login, admin    |
| `/admin/settings`    | `admin/AdminSettings.svelte` | login, admin |

There's no catch-all route, so an unknown path renders the header and footer with no page in between. nginx serves index.html for any route path that isn't a file, so deep links and reloads work on every route above. Anything under `/api/`, `/grafana` itself, and missing files with an asset extension such as `.js` don't get that fallback.

## Startup and the login guard

App.svelte calls `authStore.initialize()` in `onMount` and shows a spinner instead of the router until it finishes, whether it succeeds or fails. The route hook waits for that too:

```typescript
--8<-- "frontend/src/App.svelte:require_auth"
```

A logged-out visitor to a protected route is sent to `/login`, and the path they wanted goes into `sessionStorage` as `redirectAfterLogin`. After a successful login, Login.svelte reads and removes that key and navigates there if it's a local path (starts with `/` but not `//`, so it can't redirect off-site). Otherwise it goes to `/editor`. The API interceptor does the same when a request gets a 401 mid-session.

## Admin check

Admin routes use `requireAdmin`, which runs `requireAuth` first and then checks the role before the page component mounts:

```typescript
--8<-- "frontend/src/App.svelte:require_admin"
```

Running it as a route hook matters because each admin page starts loading its data in its own `onMount`. When the check lived only in [AdminLayout.svelte](https://github.com/HardMax71/Integr8sCode/blob/main/frontend/src/routes/admin/AdminLayout.svelte), a regular user got the page's 403 "Access denied." toast on top of "Admin access required". AdminLayout still repeats the check and shows a spinner until it passes. The backend enforces the role on every `/api/v1/admin/` endpoint anyway, so the client check is only about what the UI shows.

## Navigation

Use `goto('/path')` from the router in code and the `use:route` action on links:

```svelte
<a href="/editor" use:route>Open editor</a>
```

The admin sidebar entries come from `ADMIN_ROUTES` in `src/lib/admin/constants.ts`.
