import '@testing-library/jest-dom/vitest';
import { vi, beforeEach } from 'vitest';
import { cleanup } from '@testing-library/svelte';
import { queryClient } from '#lib/query-client.ts';

vi.useFakeTimers({ shouldAdvanceTime: true });

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

vi.mock('$app/navigation', () => ({
    goto: vi.fn(),
    beforeNavigate: vi.fn(),
    afterNavigate: vi.fn(),
    invalidateAll: vi.fn(),
}));

// The interceptors and the query client's error handler are wired up by hooks.client.ts, which tests don't run
vi.mock('#lib/api-interceptors.ts', async (importOriginal) => ({
    ...(await importOriginal<typeof import('#lib/api-interceptors.ts')>()),
    initializeApiInterceptors: vi.fn(),
}));

// Global handler for promise rejections (mirrors main.ts behavior)
// API errors are handled by interceptor - just silence the rejection in tests
process.on('unhandledRejection', () => {});

const localStorageStore: Record<string, string> = {};
const localStorageMock = {
    getItem: vi.fn((key: string) => localStorageStore[key] ?? null),
    setItem: vi.fn((key: string, value: string) => {
        localStorageStore[key] = value;
    }),
    removeItem: vi.fn((key: string) => {
        delete localStorageStore[key];
    }),
    clear: vi.fn(() => {
        Object.keys(localStorageStore).forEach((key) => delete localStorageStore[key]);
    }),
    get length() {
        return Object.keys(localStorageStore).length;
    },
    key: vi.fn((index: number) => Object.keys(localStorageStore)[index] ?? null),
};
vi.stubGlobal('localStorage', localStorageMock);

const sessionStorageStore: Record<string, string> = {};
const sessionStorageMock = {
    getItem: vi.fn((key: string) => sessionStorageStore[key] ?? null),
    setItem: vi.fn((key: string, value: string) => {
        sessionStorageStore[key] = value;
    }),
    removeItem: vi.fn((key: string) => {
        delete sessionStorageStore[key];
    }),
    clear: vi.fn(() => {
        Object.keys(sessionStorageStore).forEach((key) => delete sessionStorageStore[key]);
    }),
    get length() {
        return Object.keys(sessionStorageStore).length;
    },
    key: vi.fn((index: number) => Object.keys(sessionStorageStore)[index] ?? null),
};
vi.stubGlobal('sessionStorage', sessionStorageMock);

vi.stubGlobal(
    'matchMedia',
    vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
    })),
);

// Classes, since floating-ui (behind the bits-ui menus and popovers) constructs them with `new`
vi.stubGlobal(
    'ResizeObserver',
    class {
        observe = vi.fn();
        unobserve = vi.fn();
        disconnect = vi.fn();
    },
);

vi.stubGlobal(
    'IntersectionObserver',
    class {
        observe = vi.fn();
        unobserve = vi.fn();
        disconnect = vi.fn();
    },
);

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

Element.prototype.animate = vi.fn().mockImplementation(() => {
    const mock = {
        _onfinish: null as (() => void) | null,
        get onfinish() {
            return this._onfinish;
        },
        set onfinish(fn: (() => void) | null) {
            this._onfinish = fn;
            if (fn) queueMicrotask(fn);
        },
        cancel: vi.fn(),
        finish: vi.fn(),
        pause: vi.fn(),
        play: vi.fn(),
        reverse: vi.fn(),
        commitStyles: vi.fn(),
        persist: vi.fn(),
        currentTime: 0,
        playbackRate: 1,
        pending: false,
        playState: 'running' as AnimationPlayState,
        replaceState: 'active' as AnimationReplaceState,
        startTime: 0,
        timeline: null,
        id: '',
        effect: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(() => true),
        updatePlaybackRate: vi.fn(),
        get finished() {
            return Promise.resolve(this as unknown as Animation);
        },
        get ready() {
            return Promise.resolve(this as unknown as Animation);
        },
        oncancel: null,
        onremove: null,
    };
    return mock as unknown as Animation;
});

// Reset storage, DOM and the query cache between every test
beforeEach(() => {
    Object.keys(localStorageStore).forEach((key) => delete localStorageStore[key]);
    Object.keys(sessionStorageStore).forEach((key) => delete sessionStorageStore[key]);
    cleanup();
    queryClient.clear();
});
