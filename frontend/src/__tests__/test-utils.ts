/**
 * Shared test utilities for Vitest tests.
 */

import { onTestFinished, vi } from 'vitest';
import { configureSync, resetSync, type LogRecord } from '@logtape/logtape';
import type { Component } from 'svelte';
import { render, type RenderResult } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import QueryClientWrapper from '#test/QueryClientWrapper.svelte';
import RunInContext from '#test/RunInContext.svelte';
import type { ErrorResponse } from '#lib/api/index.ts';

export type UserEventInstance = ReturnType<typeof userEvent.setup>;

const _r = new Request('http://test');
const _s = new Response();

/** What a generated SDK function resolves with on success */
type ApiData<F> = F extends (...args: any[]) => Promise<infer R>
    ? R extends { data?: infer D }
        ? Exclude<D, undefined>
        : never
    : never;

/**
 * Fluent mock wrapper for hey-api SDK functions.
 * Hides the `request`/`response` fields that `RequestResult` requires. Like the real client, `err` rejects with an
 * ErrorResponse when the call passes `throwOnError`, which the generated query and mutation options always do.
 */
class ApiMock<F extends (...args: any[]) => any> {
    readonly mock: ReturnType<typeof vi.fn>;

    constructor(fn: F) {
        this.mock = vi.mocked(fn) as ReturnType<typeof vi.fn>;
    }

    ok(data: ApiData<F>): void {
        this.mock.mockResolvedValue({ data, error: undefined, request: _r, response: _s });
    }

    /** Answers each call from its options, such as a list filtered by the query */
    respond(handler: (...args: Parameters<F>) => ApiData<F>): void {
        this.mock.mockImplementation(async (...args: Parameters<F>) => ({
            data: handler(...args),
            error: undefined,
            request: _r,
            response: _s,
        }));
    }

    err(error: ErrorResponse): void {
        this.mock.mockImplementation((options?: { throwOnError?: boolean }) =>
            options?.throwOnError
                ? Promise.reject(error)
                : Promise.resolve({ data: undefined, error, request: _r, response: _s }),
        );
    }
}

export function mockApi<F extends (...args: any[]) => any>(fn: F): ApiMock<F> {
    return new ApiMock(fn);
}

type StreamEvent<F> = F extends (...args: any[]) => Promise<{ stream: AsyncGenerator<infer E, any, any> }> ? E : never;

async function* streamOf<E>(events: E[]): AsyncGenerator<E> {
    yield* events;
}

/** Makes a generated SSE function yield these events, then end the stream, on every call. */
export function mockStreamEvents<F extends (...args: any[]) => Promise<{ stream: AsyncGenerator<any, any, any> }>>(
    fn: F,
    ...events: StreamEvent<F>[]
): void {
    vi.mocked(fn).mockImplementation(() => Promise.resolve({ stream: streamOf(events) }) as ReturnType<F>);
}

/**
 * Calls `create` inside a component under a QueryClientProvider, the way a page creates a store that runs
 * queries. The component unmounts with `unmount()` or at the next test's cleanup.
 */
export function createInQueryContext<T>(create: () => T): { value: T; unmount: () => void } {
    let value: T | undefined;
    const { unmount } = renderWithQueryClient(RunInContext, {
        run: () => {
            value = create();
        },
    });
    return { value: value as T, unmount };
}

/** Renders a component inside the query client and tooltip providers, as the root layout does. */
export function renderWithQueryClient<Props extends Record<string, any>>(
    component: Component<Props>,
    props?: Props,
): RenderResult<typeof QueryClientWrapper> {
    return render(QueryClientWrapper, { props: { component, props } });
}

export const user: UserEventInstance = userEvent.setup({
    delay: null,
    pointerEventsCheck: 0,
});

/** Collects every record the app logs until the test ends; without this, LogTape drops them. */
export function captureLogs(): LogRecord[] {
    const records: LogRecord[] = [];
    configureSync({
        reset: true,
        sinks: { memory: (record) => records.push(record) },
        loggers: [
            { category: 'integr8scode', sinks: ['memory'] },
            { category: ['logtape', 'meta'], lowestLevel: 'warning', sinks: [] },
        ],
    });
    onTestFinished(() => {
        resetSync();
    });
    return records;
}
