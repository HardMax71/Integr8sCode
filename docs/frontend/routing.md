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
| `/admin/users`      | `routes/admin/users/+page.svelte`       | login, admin |
| `/admin/settings`   | `routes/admin/settings/+page.svelte`    | login, admin |

`(auth)` is a route group: the parentheses keep it out of the URL, and its `+layout.ts` guards every page inside. `routes/admin/+layout.svelte` is the admin sidebar around every admin page. An unknown path renders `routes/+error.svelte` with a 404. nginx serves `200.html` for any path that isn't a file, so deep links and reloads work on every route above.

## Startup and the guards

The root `+layout.ts` asks `/api/v1/auth/me` who is signed in, and SvelteKit runs it before any page renders. Its `user`, the generated `UserResponse` or `null`, is in every page's data, and components read it as `page.data.user` from `$app/state`:

```typescript
--8<-- "frontend/src/routes/+layout.ts"
```

The guards are the loads of `routes/(auth)/+layout.ts` and `routes/admin/+layout.ts`, which get that user from `parent()`:

```typescript
--8<-- "frontend/src/routes/admin/+layout.ts"
```

A signed-out visitor goes to `/login?redirect=<path>`. After a successful login, the login page checks `redirect` with `match()` and goes there if it names a page of the app, and to `/editor` otherwise. That `goto` passes `refreshAll`, so the root load runs again and picks up the new session; logout does the same on its way to `/login`. When a request gets a 401 while someone is signed in, the API interceptor shows "Session expired", empties the query cache and calls `refreshAll()`. The root load then finds nobody signed in, and a protected page's guard sends the user to `/login` with the page to come back to.

Since the guard runs in `load`, a regular user never mounts an admin page, so its admin API calls never fire and there's no "Access denied." toast on top of "Admin access required". The backend enforces the role on every `/api/v1/admin/` endpoint anyway, so the client check only decides what the UI shows.

## Navigation

Links and `goto()` take their path from `resolve()` in `$app/paths`. It type-checks the path against the app's routes and adds the base path, and ESLint's `svelte/no-navigation-without-resolve` rejects a link or `goto()` without it. A route inside a group goes by its route ID, and `resolve()` drops the group:

```svelte
<a href={resolve('/(auth)/editor')}>Open editor</a>
```

A path that only exists at runtime goes through `match()` first, which returns the route it belongs to, or null for an API path or another site; `resolve(route.id)` turns the match back into a link. The login page does that with its `redirect` parameter, and the notification dropdown with a notification's `action_url`, so neither can be sent off-site or to an API path. A link to something nginx serves instead of the app, like `/grafana`, carries `rel="external"` so the router leaves it alone.

The admin sidebar entries come from `ADMIN_ROUTES` in `src/lib/admin/constants.ts`, and the active entry follows `page.url.pathname` from `$app/state`.
