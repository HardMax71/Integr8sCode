/**
 * Shared test utilities for Vitest tests.
 *
 * Note: createMockStore must be defined inside vi.hoisted() in each test file
 * because vi.hoisted() runs before imports and cannot access external modules.
 * This is a Vitest limitation, not a design choice.
 */

import { vi } from 'vitest';

// ============================================================================
// Animation Mock for Svelte 5 Transitions
// ============================================================================

/**
 * Creates a mock Animation object compatible with Svelte 5 transitions.
 * Immediately invokes onfinish callback to simulate instant animation completion.
 */
export function createAnimationMock(): Animation {
  const mock = {
    _onfinish: null as (() => void) | null,
    get onfinish() {
      return this._onfinish;
    },
    set onfinish(fn: (() => void) | null) {
      this._onfinish = fn;
      // Immediately call onfinish to simulate instant animation completion
      if (fn) setTimeout(fn, 0);
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
}

/**
 * Sets up Element.prototype.animate mock for Svelte transitions.
 * Call this in beforeEach() for components that use transitions.
 */
export function setupAnimationMock(): void {
  Element.prototype.animate = vi.fn().mockImplementation(() => createAnimationMock());
}

// ============================================================================
// Mock Svelte Component Factory
// ============================================================================

/**
 * Creates a mock Svelte 5 component with proper $$ structure.
 * Use this for mocking child components in parent component tests.
 *
 * @param html - The HTML to render for this mock component
 * @param testId - Optional data-testid attribute
 */
export function createMockSvelteComponent(html: string, testId?: string): {
  default: { new (): object; render: () => { html: string; css: { code: string; map: null }; head: string } };
} {
  const htmlWithTestId = testId
    ? html.replace('>', ` data-testid="${testId}">`)
    : html;

  const MockComponent = function () {
    return {};
  } as unknown as { new (): object; render: () => { html: string; css: { code: string; map: null }; head: string } };

  MockComponent.render = () => ({
    html: htmlWithTestId,
    css: { code: '', map: null },
    head: '',
  });

  return { default: MockComponent };
}

// ============================================================================
// Mock Store Type (for use with vi.hoisted)
// ============================================================================

/**
 * Type definition for mock stores created with createMockStore.
 * Use this for type annotations in test files.
 */
export interface MockStore<T> {
  set(v: T): void;
  subscribe(fn: (v: T) => void): () => void;
  update(fn: (v: T) => T): void;
  _getValue?(): T;
}

/**
 * Type definition for mock derived stores.
 */
export interface MockDerivedStore<T> {
  subscribe(fn: (v: T) => void): () => void;
}

// ============================================================================
// Console Suppression Utilities
// ============================================================================

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

// ============================================================================
// Mock Store Factory Template
// ============================================================================

/**
 * Template for createMockStore function.
 * Copy this into vi.hoisted() blocks since external imports aren't allowed there.
 *
 * @example
 * const mocks = vi.hoisted(() => {
 *   function createMockStore<T>(initial: T) {
 *     let value = initial;
 *     const subscribers = new Set<(v: T) => void>();
 *     return {
 *       set(v: T) { value = v; subscribers.forEach(fn => fn(v)); },
 *       subscribe(fn: (v: T) => void) { fn(value); subscribers.add(fn); return () => subscribers.delete(fn); },
 *       update(fn: (v: T) => T) { this.set(fn(value)); },
 *     };
 *   }
 *   return { mockStore: createMockStore<string>('initial') };
 * });
 */
export const MOCK_STORE_TEMPLATE = `
function createMockStore<T>(initial: T) {
  let value = initial;
  const subscribers = new Set<(v: T) => void>();
  return {
    set(v: T) { value = v; subscribers.forEach(fn => fn(v)); },
    subscribe(fn: (v: T) => void) { fn(value); subscribers.add(fn); return () => subscribers.delete(fn); },
    update(fn: (v: T) => T) { this.set(fn(value)); },
  };
}
`;

// ============================================================================
// Mock Module Factories (for use with async vi.mock() factories)
// ============================================================================

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
    } as unknown as { new (): object; render: () => { html: string; css: { code: string; map: null }; head: string } };
    Mock.render = () => ({ html, css: { code: '', map: null }, head: '' });
    module[name] = Mock;
  }
  return module;
}

/**
 * Creates a mock @lucide/svelte module with given icon names.
 * All icons render as `<svg></svg>`.
 */
export function createMockIconModule(...iconNames: string[]): Record<string, unknown> {
  return createMockNamedComponents(
    Object.fromEntries(iconNames.map(name => [name, '<svg></svg>']))
  );
}

/**
 * Creates a mock svelte-sonner module with toast methods that delegate to addToast.
 * Usage: `vi.mock('svelte-sonner', async () => (await import('...')).createToastMock(mocks.addToast))`
 */
export function createToastMock(addToast: (...args: unknown[]) => void) {
  return {
    toast: {
      success: (...args: unknown[]) => addToast('success', ...args),
      error: (...args: unknown[]) => addToast('error', ...args),
      warning: (...args: unknown[]) => addToast('warning', ...args),
      info: (...args: unknown[]) => addToast('info', ...args),
    },
  };
}

/**
 * Creates a mock @mateothegreat/svelte5-router module.
 * If gotoFn is provided, goto calls are delegated to it for assertion tracking.
 */
export function createMockRouterModule(gotoFn?: (...args: unknown[]) => void) {
  return {
    goto: gotoFn ? (...args: unknown[]) => gotoFn(...args) : vi.fn(),
    route: () => {},
  };
}

/**
 * Creates a mock $utils/meta module with updateMetaTags and pageMeta.
 */
export function createMetaMock(
  updateMetaTagsFn: (...args: unknown[]) => void,
  pageMeta: Record<string, { title: string; description: string }>,
) {
  return {
    updateMetaTags: (...args: unknown[]) => updateMetaTagsFn(...args),
    pageMeta,
  };
}

// ============================================================================
// Test Data Factories
// ============================================================================

/**
 * Creates a mock notification for testing.
 */
export function createMockNotification(overrides: Partial<{
  notification_id: string;
  subject: string;
  body: string;
  channel: string;
  status: 'unread' | 'read';
  severity: 'low' | 'medium' | 'high' | 'urgent';
  tags: string[];
  created_at: string;
  action_url?: string;
}> = {}): {
  notification_id: string;
  subject: string;
  body: string;
  channel: string;
  status: 'unread' | 'read';
  severity: 'low' | 'medium' | 'high' | 'urgent';
  tags: string[];
  created_at: string;
  action_url?: string;
} {
  return {
    notification_id: 'notif-1',
    subject: 'Test Notification',
    body: 'This is a test notification body',
    channel: 'in_app',
    status: 'unread',
    severity: 'medium',
    tags: [],
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

/**
 * Creates multiple mock notifications for testing.
 */
export function createMockNotifications(count: number): ReturnType<typeof createMockNotification>[] {
  return Array.from({ length: count }, (_, i) =>
    createMockNotification({
      notification_id: `notif-${i + 1}`,
      subject: `Notification ${i + 1}`,
      body: `Body for notification ${i + 1}`,
      status: i % 2 === 0 ? 'unread' : 'read',
    })
  );
}
