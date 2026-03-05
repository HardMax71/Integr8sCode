import '@testing-library/jest-dom/vitest';
import { vi, beforeEach } from 'vitest';
import { cleanup } from '@testing-library/svelte';

vi.useFakeTimers({ shouldAdvanceTime: true });

vi.mock('$lib/api');

// svelte-sonner needs a factory (toast is an object with methods, not a function)
vi.mock('svelte-sonner', () => ({
    toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));

vi.mock('@mateothegreat/svelte5-router', () => ({ route: () => {}, goto: vi.fn() }));

vi.mock('$lib/api-interceptors', () => ({
    unwrap: vi.fn((result: { data?: unknown; error?: unknown }) => {
        if (result.error) throw result.error;
        if (result.data === undefined) throw new Error('Unexpected empty response');
        return result.data;
    }),
    unwrapOr: vi.fn((result: { data?: unknown; error?: unknown }, fallback: unknown) => {
        if (result.error || result.data === undefined) return fallback;
        return result.data;
    }),
    getErrorMessage: vi.fn((_err: unknown, fallback: string = 'An error occurred') => fallback),
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

vi.stubGlobal(
    'ResizeObserver',
    vi.fn().mockImplementation(() => ({
        observe: vi.fn(),
        unobserve: vi.fn(),
        disconnect: vi.fn(),
    })),
);

vi.stubGlobal(
    'IntersectionObserver',
    vi.fn().mockImplementation(() => ({
        observe: vi.fn(),
        unobserve: vi.fn(),
        disconnect: vi.fn(),
    })),
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

// Reset storage and DOM between every test (required for isolate: false)
beforeEach(() => {
    Object.keys(localStorageStore).forEach((key) => delete localStorageStore[key]);
    Object.keys(sessionStorageStore).forEach((key) => delete sessionStorageStore[key]);
    cleanup();
});
