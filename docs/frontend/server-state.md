# Frontend server state

The admin pages load and change data through [TanStack Query](https://tanstack.com/query/latest/docs/framework/svelte/overview) v6. They don't keep their own loading flags, polling loops or pagination helpers anymore. The rest of the app (editor, settings, notifications, auth) still calls the SDK directly with `unwrap` and `unwrapOr`.

The hey-api `@tanstack/svelte-query` plugin generates the options, so there's nothing to write by hand. For each GET operation it emits `xxxOptions(options)`, a query key plus a query function for `createQuery`, and `xxxQueryKey(options)`, the key alone. For each write it emits `xxxMutation()`, the mutation function for `createMutation`. They live in `src/lib/api/@tanstack/svelte-query.gen.ts` and the index re-exports them. The functions call the SDK with `throwOnError: true`, so a failed request rejects and the query ends up in its error state. Browsing events is a read sent as POST, since its filter is a body, so a `getKind` hook in `openapi-ts.config.ts` tells the plugin to treat it as a query.

`src/lib/query-client.ts` holds the one `QueryClient`, and the root layout provides it with `QueryClientProvider`. Queries don't retry. The error interceptor already toasts every failed request, so each retry would toast again.

## Reading

A store builds its queries in class fields, and the options callback reads the store's state, so a new filter, page or refresh rate is a new query key and TanStack fetches it:

```typescript
--8<-- "frontend/src/lib/admin/stores/sagasStore.svelte.ts:list"
```

Every key is its own cache entry, so a slow response for an old filter can't overwrite a newer one. `keepPreviousData` keeps the last page on screen while the next one loads. `refetchInterval` is the polling: TanStack pauses it while the tab is hidden and stops it when the page unmounts. Filter setters send the store back to the first page, since the old page may not exist under the new filter.

`isPending` is true until the first data arrives, and the tables show their spinner for it. `isFetching` is true during any request, polls included, and only drives the refresh buttons.

A detail modal loads on click with `queryClient.query(options)`, which goes through the cache and returns the data or rejects. The store catches the rejection and leaves the modal closed, since the interceptor has already shown the error. The user overview modal uses a query with `enabled` instead, because it has its own spinner and an empty state.

## Writing

Writes use the generated mutation options, and their `onSuccess` refreshes what the write changed:

```typescript
updatePriority = createMutation(() => ({
    ...updatePriorityApiV1AdminExecutionsExecutionIdPriorityPutMutation(),
    onSuccess: (_data, { body }) => {
        toast.success(`Priority updated to ${body.priority}`);
        return this.refresh();
    },
}));
```

`refresh()` invalidates the list and queue status keys, and `mutation.isPending` replaces the old `saving` and `deleting` flags. The browse events key includes its body, so there's no key prefix to invalidate. The events store refetches the list and stats on screen instead, and other pages fetch again when opened anyway.

The admin settings page and the rate limits modal edit a copy of what they loaded:

```typescript
let loaded = $derived(settingsQuery.data);
let settings = $derived.by(() => {
    const draft = $state(structuredClone(loaded ?? {}));
    return draft;
});
```

The copy never touches the cached response. Structural sharing keeps `data` the same object when a refetch returns equal data, so `loaded` doesn't change and a background refetch keeps the edits. Saving puts the response into the cache with `setQueryData`, which starts a fresh copy.
