/**
 * Shared test utilities for Vitest tests.
 */

import { vi, type Mock } from 'vitest';
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
export function mockApi<F extends (...args: any[]) => any>(fn: F) {
    const mock = vi.mocked(fn) as ReturnType<typeof vi.fn>;
    return {
        ok(data: ApiData<F>) {
            mock.mockResolvedValue({ data, error: undefined, request: _r, response: _s });
        },
        /** Answers each call from its options, such as a list filtered by the query */
        respond(handler: (...args: Parameters<F>) => ApiData<F>) {
            mock.mockImplementation(async (...args: Parameters<F>) => ({
                data: handler(...args),
                error: undefined,
                request: _r,
                response: _s,
            }));
        },
        err(error: ErrorResponse) {
            mock.mockImplementation((options?: { throwOnError?: boolean }) =>
                options?.throwOnError
                    ? Promise.reject(error)
                    : Promise.resolve({ data: undefined, error, request: _r, response: _s }),
            );
        },
        mock,
    };
}

type StreamEvent<F> = F extends (...args: any[]) => Promise<{ stream: AsyncGenerator<infer E, any, any> }> ? E : never;

/** Makes a generated SSE function yield these events, then end the stream. */
export function mockStreamEvents<F extends (...args: any[]) => Promise<{ stream: AsyncGenerator<any, any, any> }>>(
    fn: F,
    ...events: StreamEvent<F>[]
): void {
    vi.mocked(fn).mockResolvedValue({
        stream: (async function* () {
            yield* events;
        })(),
    } as Awaited<ReturnType<F>>);
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

/**
 * Suppresses console.error for the duration of a test.
 * Returns a function to restore the original behavior.
 */
export function suppressConsoleError(): () => void {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    return () => spy.mockRestore();
}

/**
 * Suppresses console.warn for the duration of a test.
 * Returns a function to restore the original behavior.
 */
export function suppressConsoleWarn(): () => void {
    const spy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    return () => spy.mockRestore();
}

/**
 * Creates a mock module with named Svelte 5 component exports.
 * Each component has proper $$ structure for Svelte 5 compatibility.
 *
 * @param components - Record mapping export names to HTML strings
 */
export function createMockNamedComponents(components: Record<string, string>): Record<string, unknown> {
    const module: Record<string, unknown> = {};
    for (const [name, html] of Object.entries(components)) {
        const Mock = function () {
            return {};
        } as unknown as {
            new (): object;
            render: () => { html: string; css: { code: string; map: null }; head: string };
        };
        Mock.render = () => ({ html, css: { code: '', map: null }, head: '' });
        module[name] = Mock;
    }
    return module;
}

export function mockWindowGlobals(openMock: Mock, confirmMock: Mock): void {
    vi.stubGlobal('open', openMock);
    vi.stubGlobal('confirm', confirmMock);
}

/**
 * Selects an option in a <select> element by value.
 *
 * Works with Svelte's bind:value in both jsdom and happy-dom.
 * Svelte reads the :checked option on change — not select.value —
 * so we must mark the <option> as selected before dispatching.
 */
export function selectOption(element: HTMLElement, value: string): void {
    const option = Array.from(element.querySelectorAll('option')).find((o) => o.value === value);
    if (!option) {
        throw new Error(`No <option value="${value}"> found`);
    }
    option.selected = true;
    element.dispatchEvent(new Event('change', { bubbles: true }));
}
