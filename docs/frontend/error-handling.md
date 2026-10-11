# Frontend error handling

API errors are shown in one place, the error interceptor in `src/lib/api-interceptors.ts`. Components don't catch them. The admin pages go through TanStack Query, whose queries and mutations land in an error state after the interceptor has toasted ([Server state](server-state.md)). The rest call `unwrap` or `unwrapOr` on the `{ data, error }` result of the generated client and let the interceptor do the toasts. A few callers check `error` themselves instead: the settings page, the notification store and the editor's execution start.

## The interceptor

`initializeApiInterceptors()` runs once, from the `init` hook in `src/hooks.client.ts`. Its error interceptor logs every failed call and picks a toast by status:

```typescript
--8<-- "frontend/src/lib/api-interceptors.ts:error_handling"
```

| Status             | What the user sees                                                       |
|--------------------|--------------------------------------------------------------------------|
| no response        | "Network error. Check your connection."                                  |
| 401                | if logged in: "Session expired. Please log in again.", auth cleared, current path saved, redirect to `/login`; otherwise auth is cleared silently |
| 403                | "Access denied."                                                         |
| 422                | "Validation error: " plus the field errors                               |
| 423                | a warning that the account is locked after too many failed logins        |
| 429                | "Too many requests. Please slow down."                                   |
| 500 and up         | "Server error. Please try again later."                                  |
| anything else      | the `detail` from the response, or "An error occurred"                   |

Calls to `/api/v1/auth/login` and `/api/v1/auth/register` get no toast for network errors or unmapped statuses, and a 401 from them leaves auth alone, because those pages show their own messages. 403, 422, 423, 429 and 5xx still toast there. A request that fails before it's sent gets no toast at all, and the error goes straight back to the caller.

The request interceptor adds `X-CSRF-Token` from `authStore.csrfToken` to every non-GET request.

## unwrap and unwrapOr

```typescript
// throws the error, so nothing after it runs
const data = unwrap(await createSavedScriptApiV1ScriptsPost({ body }));

// returns the fallback instead
const data = unwrapOr(await listSavedScriptsApiV1ScriptsGet({}), null);
```

`unwrapOr` suits loads where an empty state is fine. `unwrap` is for actions where the code after it assumes success. Reset loading flags before calling `unwrap`, since it may not return:

```typescript
saving = false;
unwrap(result);
showModal = false;   // only on success
```

`getErrorMessage(err, fallback)` turns an error into text: a string `detail`, formatted validation errors, or an `Error`'s message.

## Errors outside API calls

An error from `unwrap` inside an async click handler isn't caught by anything. The interceptor has already shown its toast, so the rejection only reaches the browser console and the page stays usable.

Errors while navigating, loading or rendering a page go to `handleError` in `src/hooks.client.ts`, which logs them, and SvelteKit renders `src/routes/+error.svelte` in place of the page. It shows `ErrorDisplay` titled "Page not found" for a 404 and "Something went wrong" otherwise, with Reload and Go to Home buttons. `ErrorDisplay` never shows raw error text; it says either that the server is unreachable or that something went wrong.

## Login and register

The login and register pages wrap their calls in `try`/`catch` and show the message from `getErrorMessage` inline, since the interceptor stays quiet on auth endpoints. `authStore.login()` throws the API error for them to catch. These two pages are the exception to the no-try/catch rule.
