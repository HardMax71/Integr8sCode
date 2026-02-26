import '@testing-library/jest-dom/vitest';
import { vi, beforeEach } from 'vitest';
import { cleanup } from '@testing-library/svelte';

// Global handler for promise rejections (mirrors main.ts behavior)
// API errors are handled by interceptor - just silence the rejection in tests
process.on('unhandledRejection', () => {});

// Mock localStorage
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
    Object.keys(localStorageStore).forEach(key => delete localStorageStore[key]);
  }),
  get length() {
    return Object.keys(localStorageStore).length;
  },
  key: vi.fn((index: number) => Object.keys(localStorageStore)[index] ?? null),
};
vi.stubGlobal('localStorage', localStorageMock);

// Mock sessionStorage
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
    Object.keys(sessionStorageStore).forEach(key => delete sessionStorageStore[key]);
  }),
  get length() {
    return Object.keys(sessionStorageStore).length;
  },
  key: vi.fn((index: number) => Object.keys(sessionStorageStore)[index] ?? null),
};
vi.stubGlobal('sessionStorage', sessionStorageMock);

// Mock matchMedia for theme tests (defaults to light mode)
vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addListener: vi.fn(),
  removeListener: vi.fn(),
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
  dispatchEvent: vi.fn(),
})));

// Mock ResizeObserver
vi.stubGlobal('ResizeObserver', vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
})));

// Mock IntersectionObserver
vi.stubGlobal('IntersectionObserver', vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
})));

// Reset DOM and storage between every test (required for isolate: false)
beforeEach(() => {
  cleanup();
  Object.keys(localStorageStore).forEach(key => delete localStorageStore[key]);
  Object.keys(sessionStorageStore).forEach(key => delete sessionStorageStore[key]);
});

// Helper to reset mocks between tests (legacy export, kept for compatibility)
export function resetStorageMocks() {
  Object.keys(localStorageStore).forEach(key => delete localStorageStore[key]);
  Object.keys(sessionStorageStore).forEach(key => delete sessionStorageStore[key]);
  vi.clearAllMocks();
}

// Mock Element.prototype.animate for Svelte transitions (canonical global stub)
// Guarded for node environment where Element is not available
if (typeof Element !== 'undefined') Element.prototype.animate = vi.fn().mockImplementation(() => {
  const mock = {
    _onfinish: null as (() => void) | null,
    get onfinish() { return this._onfinish; },
    set onfinish(fn: (() => void) | null) {
      this._onfinish = fn;
      if (fn) queueMicrotask(fn);
    },
    cancel: vi.fn(), finish: vi.fn(), pause: vi.fn(), play: vi.fn(), reverse: vi.fn(),
    commitStyles: vi.fn(), persist: vi.fn(),
    currentTime: 0, playbackRate: 1, pending: false,
    playState: 'running' as AnimationPlayState,
    replaceState: 'active' as AnimationReplaceState,
    startTime: 0, timeline: null, id: '', effect: null,
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(() => true), updatePlaybackRate: vi.fn(),
    get finished() { return Promise.resolve(this as unknown as Animation); },
    get ready() { return Promise.resolve(this as unknown as Animation); },
    oncancel: null, onremove: null,
  };
  return mock as unknown as Animation;
});
