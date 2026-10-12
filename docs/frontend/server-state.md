# Frontend server state

Every page loads and changes data through [TanStack Query](https://tanstack.com/query/latest/docs/framework/svelte/overview) v6, so none of them keeps its own loading flags, polling loops, caches or retries. The only direct SDK calls left are the three SSE streams: execution events, notifications and replay status.

The hey-api `@tanstack/svelte-query` plugin generates the options, so there's nothing to write by hand. For each GET operation it emits `xxxOptions(options)`, a query key plus a query function for `createQuery`, and `xxxQueryKey(options)`, the key alone. For each write it emits `xxxMutation()`, the mutation function for `createMutation`. They live in `src/lib/api/@tanstack/svelte-query.gen.ts` and the index re-exports them. The functions call the SDK with `throwOnError: true`, so a failed request rejects and the query ends up in its error state. Browsing events is a read sent as POST, since its filter is a body, so a `getKind` hook in `openapi-ts.config.ts` tells the plugin to treat it as a query.

`src/lib/query-client.ts` holds the one `QueryClient`, and the root layout provides it with `QueryClientProvider`. It retries a query twice on a network error or a 5xx and shows failures through its cache handlers; [Error handling](error-handling.md) covers both.

## Reading

A list page builds its query from its own state, and the options callback reads that state, so a new filter, page or refresh rate is a new query key and TanStack fetches it:

```typescript
--8<-- "frontend/src/routes/admin/sagas/+page.svelte:list"
```

Every key is its own cache entry, so a slow response for an old filter can't overwrite a newer one. `keepPreviousData` keeps the last page on screen while the next one loads. `refetchInterval` is the polling: TanStack pauses it while the tab is hidden and stops it when the page unmounts. The page size is page state and the page index is derived from the filters, so a new filter goes back to the first page, since the old page may not exist under it. The table component binds both as a TanStack Table `PaginationState`, and the query turns them into `skip` and `limit`; the table only renders the page the server sent.

`isPending` is true until the first data arrives, and the tables show their spinner for it. `isFetching` is true during any request, polls included, and only drives the refresh buttons.

A component fetches what only it shows. The page keeps the id of the open saga or event, and the detail modal runs the query for it; following a related event changes the id, which is a new key. A failed load closes the modal, since the interceptor has already shown the error. The replay banner follows the replay status stream while it's mounted, and closing it aborts the stream.

## Writing

Writes use the generated mutation options, and their `onSuccess` refreshes what the write changed:

```typescript
const updatePriority = createMutation(() => ({
    ...updatePriorityApiV1AdminExecutionsExecutionIdPriorityPutMutation(),
    onSuccess: (_data, { body }) => {
        toast.success(`Priority updated to ${body.priority}`);
        return Promise.all([
            queryClient.invalidateQueries({ queryKey: listExecutionsApiV1AdminExecutionsGetQueryKey() }),
            queryClient.invalidateQueries({ queryKey: getQueueStatusApiV1AdminExecutionsQueueGetQueryKey() }),
        ]);
    },
}));
```

The mutation lives in the executions table, which renders the priority select, and invalidates the list and queue status keys. `mutation.isPending` replaces the old `saving` and `deleting` flags. The browse events key includes its body, so there's no key prefix to invalidate; the events page refetches the list and stats on screen instead, and other pages fetch again when opened anyway.

The two settings pages are superforms forms on the generated Zod schemas, and an effect starts the form over from whatever the query holds:

```typescript
$effect(() => {
    if (settingsQuery.data) form.reset({ newState: settingsQuery.data });
});
```

The form keeps its own copy, so edits never touch the cached response. When a refetch returns equal data, the query keeps the old `data` object, so the effect doesn't run again and a background refetch keeps the edits. Saving, resetting or restoring puts the response into the cache with `setQueryData`, which starts the form over from it. The rate limits modal still edits a `structuredClone` of what it loaded until its rules have a schema (#290).

## Session and user settings

The auth store isn't a component, so it uses the client directly. `verifyAuth()` asks `queryClient.query()` for the profile with a 30 second stale time, which replaces the store's own cache: checks within 30 seconds share one answer, and checks made at the same time share one request. `clearAuth()` empties the cache. Login and logout are mutations in the login page and the header.

User settings are one query, `getUserSettingsApiV1UserSettingsGetOptions()`, read wherever they're needed. The root layout applies the saved theme from it, the editor takes its editor settings from it, and the settings page's form starts from it. Saving or restoring puts the response into that query with `setQueryData`, so every reader sees the new settings at once. The header's theme toggle saves the theme the same way.

New notifications arrive over SSE. The notification center refetches the notification queries on each one instead of patching the list, so the unread count always comes from the server.
