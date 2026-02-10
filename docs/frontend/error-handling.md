# Error handling

The frontend uses a centralized error handling pattern built around two helpers: `unwrap` and `unwrapOr`. These work with the `{ data, error }` result structure returned by the generated API client.

## Why this exists

The API client returns results in a discriminated union format where every call gives you `{ data, error }`. The naive approach leads to repetitive boilerplate scattered across every component:

```typescript
const { data, error } = await someApiCall({});
if (error) return;
doSomething(data);
```

This `if (error) return` pattern appeared 17+ times across admin panels and the editor. It's noisy, easy to forget, and obscures the actual logic. The helpers eliminate it while keeping the code readable.

## How it works

Both helpers live in `lib/api-interceptors.ts` alongside the centralized error interceptor that shows toast notifications for API failures.

`unwrap` extracts the data or throws if there's an error:

```typescript
const data = unwrap(await listUsersApiV1AdminUsersGet({}));
// data is guaranteed to exist here - if there was an error, we threw
users = data;
```

When the API call fails, the interceptor has already shown a toast to the user. The throw stops the function execution - any code after `unwrap` only runs on success. The thrown error bubbles up as an unhandled rejection, gets logged to console, and that's it.

`unwrapOr` returns a fallback value instead of throwing:

```typescript
const data = unwrapOr(await listUsersApiV1AdminUsersGet({}), null);
users = data ? data : [];
```

This is useful when you want to continue execution with a default value rather than bail out entirely. Common for load functions where an empty array is a reasonable fallback.

## Choosing between them

Use `unwrap` when the function should stop on error. Delete operations, save operations, anything where subsequent code assumes success:

```typescript
async function deleteUser(): Promise<void> {
    deletingUser = true;
    const result = await deleteUserApiV1AdminUsersUserIdDelete({ path: { user_id } });
    deletingUser = false;
    unwrap(result);
    // only runs if delete succeeded
    await loadUsers();
    showModal = false;
}
```

Use `unwrapOr` when you can gracefully handle failure with a default. Load operations where showing an empty state is acceptable:

```typescript
async function loadEvents() {
    loading = true;
    const data = unwrapOr(await browseEventsApiV1AdminEventsBrowsePost({ body: filters }), null);
    loading = false;
    events = data?.events || [];
}
```

## Cleanup before unwrap

If you need cleanup to run regardless of success or failure (like resetting a loading flag), do it before calling `unwrap`:

```typescript
async function saveRateLimits(): Promise<void> {
    savingRateLimits = true;
    const result = await updateRateLimitsApi({ body: config });
    savingRateLimits = false;  // runs whether or not there's an error
    unwrap(result);            // throws if error, stopping execution
    showModal = false;         // only runs on success
}
```

The pattern is: await the call, do cleanup, then unwrap. This keeps the loading state correct even when errors occur.

## What happens on error

The error interceptor in `api-interceptors.ts` handles user feedback. When an API call fails, it shows an appropriate toast based on the status code (401 redirects to login, 403 shows access denied, 422 formats validation errors, 423 warns about account lockout, 429 warns about rate limits, 5xx shows server error). By the time your component code sees the error, the user has already been notified.

The `unwrap` throw becomes an unhandled promise rejection. The global handler in `main.ts` logs it to console and suppresses the default browser error. No error page, no duplicate notifications - just a clean exit from the function.
