# Frontend routing

The frontend uses SvelteKit's filesystem router. Each page is a `+page.svelte` under `frontend/src/routes/`, and the login and admin checks are `load` functions in `+layout.ts` files, which run before the page mounts.

## Routes

| Path                | File                                    | Guard        |
|---------------------|-----------------------------------------|--------------|
| `/`                 | `routes/+page.svelte`                   | none         |
| `/login`            | `routes/login/+page.svelte`             | none         |
| `/register`         | `routes/register/+page.svelte`          | none         |
| `/privacy`          | `routes/privacy/+page.svelte`           | none         |
| `/editor`           | `routes/(auth)/editor/+page.svelte`     | login        |
| `/settings`         | `routes/(auth)/settings/+page.svelte`   | login        |
| `/notifications`    | `routes/(auth)/notifications/+page.svelte` | login     |
| `/admin`            | `routes/admin/+page.ts`, redirects to `/admin/events` | login, admin |
| `/admin/events`     | `routes/admin/events/+page.svelte`      | login, admin |
| `/admin/executions` | `routes/admin/executions/+page.svelte`  | login, admin |
| `/admin/sagas`      | `routes/admin/sagas/+page.svelte`       | login, admin |
| `/admin/users`      | `routes/admin/users/+page.svelte`       | login, admin |
| `/admin/settings`   | `routes/admin/settings/+page.svelte`    | login, admin |

`(auth)` is a route group: the parentheses keep it out of the URL, and its `+layout.ts` guards every page inside. `routes/admin/+layout.svelte` is the admin sidebar around every admin page. An unknown path renders `routes/+error.svelte` with a 404. nginx serves `200.html` for any path that isn't a file, so deep links and reloads work on every route above.

## Startup and the guards

The root layout calls `authStore.initialize()` in `onMount` and shows a spinner instead of the page until it finishes, whether it succeeds or fails. The guards wait for the same check:

```typescript
--8<-- "frontend/src/lib/auth-guard.ts"
```

`routes/(auth)/+layout.ts` calls `requireAuth` and `routes/admin/+layout.ts` calls `requireAdmin`. A signed-out visitor is redirected to `/login`, and the path they wanted goes into `sessionStorage` as `redirectAfterLogin`. After a successful login, the login page reads and removes that key and navigates there if it's a local path (starts with `/` but not `//`, so it can't redirect off-site). Otherwise it goes to `/editor`. The API interceptor does the same when a request gets a 401 mid-session.

Since the guard runs in `load`, a regular user never mounts an admin page, so its admin API calls never fire and there's no "Access denied." toast on top of "Admin access required". The backend enforces the role on every `/api/v1/admin/` endpoint anyway, so the client check only decides what the UI shows.

## Navigation

Use plain links; SvelteKit handles same-origin `<a href>` clicks itself:

```svelte
<a href="/editor">Open editor</a>
```

In code, use `goto('/path')` from `$app/navigation`. It returns a promise and rejects for a URL that isn't a route in the app; use `window.location.href` for an external one. The admin sidebar entries come from `ADMIN_ROUTES` in `src/lib/admin/constants.ts`, and the active entry follows `page.url.pathname` from `$app/state`.
