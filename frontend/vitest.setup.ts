import '@testing-library/jest-dom/vitest';
import { vi, beforeEach } from 'vitest';
import { faker } from '@faker-js/faker';
import { queryClient } from '#lib/query-client.ts';
import { page } from '#test/page.svelte.ts';

// SDK calls become mocks, both through the index and through the generated query options, which import
// sdk.gen directly; enums, Zod schemas, the client and the query options themselves stay real
vi.mock('#lib/api/sdk.gen.ts', async (importOriginal) => {
    const actual = await importOriginal<typeof import('#lib/api/sdk.gen.ts')>();
    return Object.fromEntries(
        Object.entries(actual).map(([name, value]) => [name, typeof value === 'function' ? vi.fn() : value]),
    );
});

// svelte-sonner needs a factory (toast is an object with methods, not a function)
vi.mock('svelte-sonner', () => ({
    toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));

// match() reads the router of a started app, which unit tests don't have, so a test sets the route it returns
vi.mock('$app/paths', async (importOriginal) => ({
    ...(await importOriginal<typeof import('$app/paths')>()),
    match: vi.fn(),
}));

// page needs a running app, so it's the stand-in a test sets: signed out on the home page by default
vi.mock('$app/state', async (importOriginal) => ({
    ...(await importOriginal<typeof import('$app/state')>()),
    page: (await import('#test/page.svelte.ts')).page,
}));

vi.mock('$app/navigation', () => ({
    goto: vi.fn(),
    beforeNavigate: vi.fn(),
    afterNavigate: vi.fn(),
    refreshAll: vi.fn(),
}));

// The interceptors and the query client's error handler are wired up by hooks.client.ts, which tests don't run
vi.mock('#lib/api-interceptors.ts', async (importOriginal) => ({
    ...(await importOriginal<typeof import('#lib/api-interceptors.ts')>()),
    initializeApiInterceptors: vi.fn(),
}));

// Polyfill :checked for <option> elements (happy-dom doesn't support it).
// Svelte's bind_select_value reads select.querySelector(':checked') on change events,
// so without this polyfill bind:value never updates in tests.
{
    const origQS = HTMLSelectElement.prototype.querySelector;
    HTMLSelectElement.prototype.querySelector = function (selector: string) {
        if (selector === ':checked') {
            for (const opt of this.options) {
                if (opt.selected) return opt;
            }
            return null;
        }
        return origQS.call(this, selector);
    } as typeof origQS;

    const origQSA = HTMLSelectElement.prototype.querySelectorAll;
    HTMLSelectElement.prototype.querySelectorAll = function (selector: string) {
        if (selector === ':checked') {
            return Array.from(this.options).filter((o) => o.selected) as unknown as ReturnType<typeof origQSA>;
        }
        return origQSA.call(this, selector);
    } as typeof origQSA;
}

class FakeAnimation {
    _onfinish: (() => void) | null = null;
    get onfinish(): (() => void) | null {
        return this._onfinish;
    }
    set onfinish(fn: (() => void) | null) {
        this._onfinish = fn;
        if (fn) queueMicrotask(fn);
    }
    cancel = vi.fn();
    finish = vi.fn();
    pause = vi.fn();
    play = vi.fn();
    reverse = vi.fn();
    commitStyles = vi.fn();
    persist = vi.fn();
    currentTime = 0;
    playbackRate = 1;
    pending = false;
    playState: AnimationPlayState = 'running';
    replaceState: AnimationReplaceState = 'active';
    startTime = 0;
    timeline = null;
    id = '';
    effect = null;
    addEventListener = vi.fn();
    removeEventListener = vi.fn();
    dispatchEvent = vi.fn(() => true);
    updatePlaybackRate = vi.fn();
    get finished(): Promise<FakeAnimation> {
        return Promise.resolve(this);
    }
    get ready(): Promise<FakeAnimation> {
        return Promise.resolve(this);
    }
    oncancel = null;
    onremove = null;
}

Element.prototype.animate = vi.fn(() => new FakeAnimation() as unknown as Animation);

// A class, since floating-ui (behind the bits-ui menus and popovers) constructs observers with `new`
class NoopObserver {
    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
}

function unmatchedQuery(query: string): MediaQueryList {
    return {
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
    };
}

// The generated fakes use the shared faker instance, so a fixed seed and date give each test the same fixtures every run
faker.setDefaultRefDate('2026-01-01T00:00:00Z');
faker.seed(1);

// The config undoes every vi.stubGlobal before each test, so the stubs are set here, after it
beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.stubGlobal('matchMedia', vi.fn(unmatchedQuery));
    vi.stubGlobal('ResizeObserver', NoopObserver);
    vi.stubGlobal('IntersectionObserver', NoopObserver);
    localStorage.clear();
    page.url = new URL('https://localhost/');
    page.data = { user: null };
    queryClient.clear();
    faker.seed(1);
});
