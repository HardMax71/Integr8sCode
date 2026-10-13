# Frontend error handling

API errors are shown in one place, and components don't catch them. Every request goes through TanStack Query ([Server state](server-state.md)), so a failure ends up in a query's or mutation's error state, and the query client's cache handlers show it. The three SSE streams are the exception: they report a dropped stream themselves.

## From response to toast

The generated query and mutation options call the SDK with `throwOnError`, which throws the response body. Every error the backend sends is an `ErrorResponse`, `{status, detail}`, so that body already carries the status and nothing wraps it. The error interceptor in `src/lib/api-interceptors.ts` logs each failure and fills in the ones without such a body: anything else, like a proxy's error page, becomes `{status, detail: "HTTP <status>"}`, and a request that got no response, or never went out, becomes status 0 with "Network error. Check your connection.". `ErrorResponse` is registered as TanStack Query's `defaultError`, so every query and mutation error is typed as it.

The query client in `src/lib/query-client.ts` retries a query twice when the error is a network failure or a 5xx, waiting 1 second and then 2. Mutations never retry, since a write may not be safe to repeat. Once a query has used up its retries, or a mutation fails, the cache's `onError` calls `showApiError`, which picks the toast by status. The client gets that handler from `initializeApiInterceptors()`, which runs from the `init` hook in `src/hooks.client.ts`. It's handed over at startup instead of imported, because the auth store imports the query client and `api-interceptors.ts` imports the auth store.

```typescript
--8<-- "frontend/src/lib/api-interceptors.ts:error_handling"
```

| Status             | What the user sees                                                       |
|--------------------|--------------------------------------------------------------------------|
| 0 (no response)    | "Network error. Check your connection."                                  |
| 401                | if logged in: "Session expired. Please log in again.", auth cleared, current path saved, redirect to `/login`; otherwise auth is cleared silently |
| 403                | "Access denied."                                                         |
| 422                | "Validation error: " plus the `detail`, which lists the fields          |
| 423                | a warning that the account is locked after too many failed logins        |
| 429                | "Too many requests. Please slow down."                                   |
| 500 and up         | "Server error. Please try again later."                                  |
| anything else      | the `detail` from the response                                           |

Clearing auth also empties the query cache, so nothing the previous user loaded shows to the next one.

The request interceptor adds `X-CSRF-Token` from the signed-in session to every non-GET request.

## Forms that show their own errors

The login and register pages show the error under the form, so their mutations carry `meta: { inlineErrors: true }`. For those, `showApiError` skips the network toast, the 401 handling and the `detail` toast for other 4xx, and the page renders `mutation.error.detail` instead. 403, 422, 423, 429 and 5xx still toast, since their messages are the same everywhere.

A component that needs to react to one specific failure passes `onError` to `mutate`. The editor does this when saving a script that was deleted elsewhere: a 404 from the update means it creates the script instead. The toast still comes from the cache handler.

## Errors outside API calls

Errors while navigating, loading or rendering a page go to `handleError` in `src/hooks.client.ts`, which logs them, and SvelteKit renders `src/routes/+error.svelte` in place of the page. It shows `ErrorDisplay` titled "Page not found" for a 404 and "Something went wrong" otherwise, with Reload and Go to Home buttons. `ErrorDisplay` never shows raw error text; it says either that the server is unreachable or that something went wrong.
