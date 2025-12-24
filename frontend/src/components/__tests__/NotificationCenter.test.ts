import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { setupAnimationMock } from '../../__tests__/test-utils';

// Types for mock notification state
interface MockNotification {
  notification_id: string;
  subject: string;
  body: string;
  status: 'unread' | 'read';
  severity: 'low' | 'medium' | 'high' | 'urgent';
  tags: string[];
  created_at: string;
  action_url?: string;
}

// vi.hoisted must contain self-contained code - cannot import external modules
const mocks = vi.hoisted(() => {
  function createMockStore<T>(initial: T) {
    let value = initial;
    const subscribers = new Set<(v: T) => void>();
    return {
      set(v: T) { value = v; subscribers.forEach(fn => fn(v)); },
      subscribe(fn: (v: T) => void) { fn(value); subscribers.add(fn); return () => subscribers.delete(fn); },
      update(fn: (v: T) => T) { this.set(fn(value)); },
      _getValue() { return value; },
    };
  }

  function createDerivedStore<T, R>(
    source: { subscribe: (fn: (v: T) => void) => () => void; _getValue: () => T },
    fn: (v: T) => R
  ) {
    const subscribers = new Set<(v: R) => void>();
    let currentValue = fn(source._getValue());
    source.subscribe((v) => { currentValue = fn(v); subscribers.forEach(sub => sub(currentValue)); });
    return { subscribe(callback: (v: R) => void) { callback(currentValue); subscribers.add(callback); return () => subscribers.delete(callback); } };
  }

  type NotifState = { notifications: MockNotification[]; loading: boolean; error: string | null };
  const mockNotificationsState = createMockStore<NotifState>({ notifications: [], loading: false, error: null });

  return {
    mockIsAuthenticated: createMockStore<boolean | null>(true),
    mockUsername: createMockStore<string | null>('testuser'),
    mockUserId: createMockStore<string | null>('user-123'),
    mockNotificationsState,
    mockNotifications: createDerivedStore(mockNotificationsState, s => s.notifications),
    mockUnreadCount: createDerivedStore(mockNotificationsState, s => s.notifications.filter(n => n.status !== 'read').length),
    mockGoto: null as unknown as ReturnType<typeof vi.fn>,
    mockNotificationStore: null as unknown as {
      subscribe: typeof mockNotificationsState.subscribe;
      load: ReturnType<typeof vi.fn>;
      add: ReturnType<typeof vi.fn>;
      markAsRead: ReturnType<typeof vi.fn>;
      markAllAsRead: ReturnType<typeof vi.fn>;
      delete: ReturnType<typeof vi.fn>;
      clear: ReturnType<typeof vi.fn>;
      refresh: ReturnType<typeof vi.fn>;
    },
  };
});

// Initialize mocks
mocks.mockGoto = vi.fn();
mocks.mockNotificationStore = {
  subscribe: mocks.mockNotificationsState.subscribe,
  load: vi.fn().mockResolvedValue([]),
  add: vi.fn(),
  markAsRead: vi.fn().mockResolvedValue(true),
  markAllAsRead: vi.fn().mockResolvedValue(true),
  delete: vi.fn().mockResolvedValue(true),
  clear: vi.fn(),
  refresh: vi.fn(),
};

vi.mock('@mateothegreat/svelte5-router', () => ({ get goto() { return (...args: unknown[]) => mocks.mockGoto(...args); } }));
vi.mock('../../stores/auth', () => ({
  get isAuthenticated() { return mocks.mockIsAuthenticated; },
  get username() { return mocks.mockUsername; },
  get userId() { return mocks.mockUserId; },
}));
vi.mock('../../stores/notificationStore', () => ({
  get notificationStore() { return mocks.mockNotificationStore; },
  get notifications() { return mocks.mockNotifications; },
  get unreadCount() { return mocks.mockUnreadCount; },
}));

// Mock EventSource with instance tracking
class MockEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  static instances: MockEventSource[] = [];

  readyState = MockEventSource.OPEN;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;

  constructor(public url: string, public options?: { withCredentials?: boolean }) {
    MockEventSource.instances.push(this);
    setTimeout(() => { if (this.onopen) this.onopen(new Event('open')); }, 0);
  }

  close() { this.readyState = MockEventSource.CLOSED; }

  simulateMessage(data: unknown) {
    if (this.onmessage) {
      this.onmessage(new MessageEvent('message', { data: JSON.stringify(data) }));
    }
  }

  simulateError() {
    if (this.onerror) {
      this.onerror(new Event('error'));
    }
  }

  static clearInstances() { MockEventSource.instances = []; }
  static getLastInstance(): MockEventSource | undefined {
    return MockEventSource.instances[MockEventSource.instances.length - 1];
  }
}
vi.stubGlobal('EventSource', MockEventSource);
vi.stubGlobal('Notification', { permission: 'default', requestPermission: vi.fn().mockResolvedValue('granted') });

import NotificationCenter from '../NotificationCenter.svelte';

// =============================================================================
// Test Helpers
// =============================================================================

const createNotification = (overrides: Partial<MockNotification> = {}): MockNotification => ({
  notification_id: '1',
  subject: 'Test',
  body: 'Body',
  status: 'unread',
  severity: 'medium',
  tags: [],
  created_at: new Date().toISOString(),
  ...overrides,
});

const setNotifications = (notifications: MockNotification[]) => {
  mocks.mockNotificationsState.set({ notifications, loading: false, error: null });
};

const openDropdown = async () => {
  const user = userEvent.setup();
  render(NotificationCenter);
  await user.click(screen.getByRole('button', { name: /Notifications/i }));
  return user;
};

const openDropdownWithContainer = async () => {
  const user = userEvent.setup();
  const { container } = render(NotificationCenter);
  await user.click(screen.getByRole('button', { name: /Notifications/i }));
  return { user, container };
};

/** Sets up SSE and waits for the EventSource to be ready with handlers attached */
const setupSSE = async () => {
  mocks.mockIsAuthenticated.set(true);
  render(NotificationCenter);
  await waitFor(() => { expect(MockEventSource.instances.length).toBeGreaterThan(0); });
  const instance = MockEventSource.getLastInstance()!;
  await waitFor(() => { expect(instance.onmessage).not.toBeNull(); });
  return instance;
};

/** Mocks window.location.href for external URL testing */
const withMockedLocation = async (testFn: (mockHref: ReturnType<typeof vi.fn>) => Promise<void>) => {
  const originalLocation = window.location;
  const mockHref = vi.fn();
  Object.defineProperty(window, 'location', { value: { ...originalLocation, href: '' }, writable: true, configurable: true });
  Object.defineProperty(window.location, 'href', { set: mockHref, configurable: true });
  try {
    await testFn(mockHref);
  } finally {
    Object.defineProperty(window, 'location', { value: originalLocation, writable: true, configurable: true });
  }
};

// =============================================================================
// Test Data
// =============================================================================

/** Icon test cases: tags -> expected SVG path fragment */
const iconTestCases = [
  { tags: ['completed'], subject: 'Completed', svgPath: 'M9 12l2 2 4-4', desc: 'check icon' },
  { tags: ['success'], subject: 'Success', svgPath: 'M9 12l2 2 4-4', desc: 'check icon' },
  { tags: ['failed'], subject: 'Failed', svgPath: 'M12 8v4m0 4h.01', desc: 'error icon' },
  { tags: ['error'], subject: 'Error', svgPath: 'M12 8v4m0 4h.01', desc: 'error icon' },
  { tags: ['security'], subject: 'Security', svgPath: 'M12 8v4m0 4h.01', desc: 'error icon' },
  { tags: ['timeout'], subject: 'Timeout', svgPath: 'M12 9v2m0 4h.01', desc: 'warning icon' },
  { tags: ['warning'], subject: 'Warning', svgPath: 'M12 9v2m0 4h.01', desc: 'warning icon' },
  { tags: ['unknown'], subject: 'Unknown', svgPath: 'M13 16h-1v-4h-1', desc: 'info icon (default)' },
  { tags: [], subject: 'NoTags', svgPath: 'M13 16h-1v-4h-1', desc: 'info icon (no tags)' },
];

/** Priority color test cases */
const priorityColorTestCases = [
  { severity: 'low' as const, colorClass: '.text-gray-600', desc: 'gray for low' },
  { severity: 'medium' as const, colorClass: '.text-blue-600', desc: 'blue for medium' },
  { severity: 'high' as const, colorClass: '.text-orange-600', desc: 'orange for high' },
  { severity: 'urgent' as const, colorClass: '.text-red-600', desc: 'red for urgent' },
];

/** Time formatting test cases */
const timeFormatTestCases = [
  { offsetMs: 0, expected: 'just now' },
  { offsetMs: 5 * 60 * 1000, expected: '5m ago' },
  { offsetMs: 3 * 60 * 60 * 1000, expected: '3h ago' },
];

/** Badge count test cases */
const badgeCountTestCases = [
  { count: 2, expected: '2' },
  { count: 9, expected: '9' },
  { count: 12, expected: '9+' },
];

/** SSE messages that should be ignored (not added to store) */
const ignoredSSEMessages = [
  { message: { event: 'heartbeat' }, desc: 'heartbeat' },
  { message: { event: 'connected' }, desc: 'connected' },
  { message: { some_other_field: 'value' }, desc: 'non-notification event', shouldLog: true },
];

// =============================================================================
// Tests
// =============================================================================

describe('NotificationCenter', () => {
  beforeEach(() => {
    setupAnimationMock();
    mocks.mockIsAuthenticated.set(true);
    mocks.mockUsername.set('testuser');
    mocks.mockUserId.set('user-123');
    setNotifications([]);
    mocks.mockGoto.mockReset();
    mocks.mockNotificationStore.load.mockReset().mockResolvedValue([]);
    mocks.mockNotificationStore.markAsRead.mockReset().mockResolvedValue(true);
    mocks.mockNotificationStore.markAllAsRead.mockReset().mockResolvedValue(true);
    mocks.mockNotificationStore.clear.mockReset();
    mocks.mockNotificationStore.add.mockReset();
    MockEventSource.clearInstances();
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.spyOn(console, 'debug').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => { vi.restoreAllMocks(); });

  describe('bell icon and badge', () => {
    it('renders notification button with bell icon', () => {
      render(NotificationCenter);
      const button = screen.getByRole('button', { name: /Notifications/i });
      expect(button).toBeInTheDocument();
      expect(button.querySelector('svg')).toBeInTheDocument();
    });

    it('shows no badge when no unread notifications', () => {
      const { container } = render(NotificationCenter);
      expect(container.querySelector('.bg-red-500')).not.toBeInTheDocument();
    });

    it.each(badgeCountTestCases)(
      'shows badge "$expected" when $count unread notifications',
      async ({ count, expected }) => {
        setNotifications(Array.from({ length: count }, (_, i) =>
          createNotification({ notification_id: String(i), subject: `Test ${i}` })
        ));
        const { container } = render(NotificationCenter);
        await waitFor(() => { expect(container.querySelector('.bg-red-500')?.textContent).toBe(expected); });
      }
    );
  });

  describe('dropdown behavior', () => {
    it('opens dropdown when bell clicked', async () => {
      await openDropdown();
      await waitFor(() => { expect(screen.getByText('Notifications')).toBeInTheDocument(); });
    });

    it('shows empty state when no notifications', async () => {
      await openDropdown();
      await waitFor(() => { expect(screen.getByText('No notifications yet')).toBeInTheDocument(); });
    });

    it('navigates to /notifications when View all clicked', async () => {
      const user = await openDropdown();
      await waitFor(() => { expect(screen.getByText('View all notifications')).toBeInTheDocument(); });
      await user.click(screen.getByText('View all notifications'));
      expect(mocks.mockGoto).toHaveBeenCalledWith('/notifications');
    });
  });

  describe('notification list display', () => {
    const sampleNotifications = [
      createNotification({ notification_id: '1', subject: 'Build Completed', body: 'Your build finished' }),
      createNotification({ notification_id: '2', subject: 'Build Failed', body: 'Build error', status: 'read' }),
    ];

    it('displays notification subjects and bodies', async () => {
      setNotifications(sampleNotifications);
      await openDropdown();
      await waitFor(() => {
        expect(screen.getByText('Build Completed')).toBeInTheDocument();
        expect(screen.getByText('Build Failed')).toBeInTheDocument();
      });
    });

    it('shows unread indicator for unread notifications', async () => {
      setNotifications(sampleNotifications);
      const { container } = await openDropdownWithContainer();
      await waitFor(() => {
        expect(container.querySelectorAll('.bg-blue-500.rounded-full').length).toBeGreaterThan(0);
        expect(container.querySelector('.bg-blue-50')).toBeInTheDocument();
      });
    });
  });

  describe('mark as read functionality', () => {
    it.each([
      { status: 'unread' as const, shouldShow: true },
      { status: 'read' as const, shouldShow: false },
    ])('$status notifications: Mark all button visible=$shouldShow', async ({ status, shouldShow }) => {
      setNotifications([createNotification({ status })]);
      await openDropdown();
      await waitFor(() => {
        const button = screen.queryByText('Mark all as read');
        expect(shouldShow ? button : !button).toBeTruthy();
      });
    });

    it('calls markAllAsRead and closes dropdown', async () => {
      setNotifications([createNotification()]);
      const user = await openDropdown();
      await user.click(await screen.findByText('Mark all as read'));
      expect(mocks.mockNotificationStore.markAllAsRead).toHaveBeenCalled();
    });

    it('does not call markAsRead for already-read notifications', async () => {
      setNotifications([createNotification({ subject: 'AlreadyRead', status: 'read' })]);
      const user = await openDropdown();
      await user.click(await screen.findByRole('button', { name: /View notification: AlreadyRead/i }));
      expect(mocks.mockNotificationStore.markAsRead).not.toHaveBeenCalled();
    });
  });

  describe('notification icons', () => {
    it.each(iconTestCases)(
      'shows $desc for tags=$tags',
      async ({ tags, subject, svgPath }) => {
        setNotifications([createNotification({ tags, subject })]);
        const { container } = await openDropdownWithContainer();
        await waitFor(() => {
          const item = container.querySelector(`[role="button"][aria-label*="${subject}"]`);
          expect(item?.querySelector('svg')?.innerHTML).toContain(svgPath);
        });
      }
    );
  });

  describe('priority colors', () => {
    it.each(priorityColorTestCases)(
      'applies $desc ($colorClass)',
      async ({ severity, colorClass }) => {
        setNotifications([createNotification({ severity, subject: severity })]);
        const { container } = await openDropdownWithContainer();
        await waitFor(() => { expect(container.querySelector(colorClass)).toBeInTheDocument(); });
      }
    );
  });

  describe('time formatting', () => {
    it.each(timeFormatTestCases)(
      'shows "$expected" for notifications $offsetMs ms ago',
      async ({ offsetMs, expected }) => {
        setNotifications([createNotification({ created_at: new Date(Date.now() - offsetMs).toISOString() })]);
        await openDropdown();
        await waitFor(() => { expect(screen.getByText(expected)).toBeInTheDocument(); });
      }
    );

    it('shows date for notifications older than 24 hours', async () => {
      const oldDate = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000);
      setNotifications([createNotification({ created_at: oldDate.toISOString() })]);
      await openDropdown();
      await waitFor(() => { expect(screen.getByText(oldDate.toLocaleDateString())).toBeInTheDocument(); });
    });
  });

  describe('notification interaction', () => {
    it.each([
      { method: 'click', hasUrl: true, url: '/builds/123' },
      { method: 'click', hasUrl: false, url: undefined },
      { method: 'keyboard', hasUrl: true, url: '/test' },
      { method: 'keyboard', hasUrl: false, url: undefined },
    ])('$method interaction: navigates=$hasUrl', async ({ method, hasUrl, url }) => {
      const subject = `${method}-${hasUrl}`;
      setNotifications([createNotification({ subject, action_url: url })]);
      const user = await openDropdown();
      await waitFor(() => { expect(screen.getByText(subject)).toBeInTheDocument(); });

      const button = screen.getByRole('button', { name: new RegExp(`View notification: ${subject}`, 'i') });
      if (method === 'click') {
        await user.click(button);
      } else {
        button.focus();
        await user.keyboard('{Enter}');
      }

      expect(mocks.mockNotificationStore.markAsRead).toHaveBeenCalledWith('1');
      if (hasUrl) {
        expect(mocks.mockGoto).toHaveBeenCalledWith(url);
      } else {
        expect(mocks.mockGoto).not.toHaveBeenCalled();
      }
    });

    it('ignores non-Enter keydown events', async () => {
      vi.useFakeTimers();
      setNotifications([createNotification({ subject: 'KeyTest', action_url: '/test' })]);
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      render(NotificationCenter);
      await user.click(screen.getByRole('button', { name: /Notifications/i }));
      await waitFor(() => { expect(screen.getByText('KeyTest')).toBeInTheDocument(); });

      screen.getByRole('button', { name: /View notification: KeyTest/i }).focus();
      await user.keyboard('{Tab}');

      expect(mocks.mockNotificationStore.markAsRead).not.toHaveBeenCalled();
      expect(mocks.mockGoto).not.toHaveBeenCalled();
      vi.useRealTimers();
    });
  });

  describe('external URL navigation', () => {
    it.each([
      { method: 'click' as const },
      { method: 'keyboard' as const },
    ])('navigates to external URL via $method', async ({ method }) => {
      await withMockedLocation(async (mockHref) => {
        const subject = `External-${method}`;
        const url = `https://example.com/${method}`;
        setNotifications([createNotification({ subject, action_url: url })]);
        const user = await openDropdown();
        await waitFor(() => { expect(screen.getByText(subject)).toBeInTheDocument(); });

        const button = screen.getByRole('button', { name: new RegExp(`View notification: ${subject}`, 'i') });
        if (method === 'click') {
          await user.click(button);
        } else {
          button.focus();
          await user.keyboard('{Enter}');
        }
        expect(mockHref).toHaveBeenCalledWith(url);
      });
    });
  });

  describe('accessibility', () => {
    it('has aria-label on notification button', () => {
      render(NotificationCenter);
      expect(screen.getByRole('button', { name: /Notifications/i })).toHaveAttribute('aria-label', 'Notifications');
    });

    it('notification items are focusable with proper aria-label', async () => {
      setNotifications([createNotification({ subject: 'Test Subject' })]);
      await openDropdown();
      await waitFor(() => {
        const item = screen.getByRole('button', { name: /View notification: Test Subject/i });
        expect(item).toHaveAttribute('tabindex', '0');
      });
    });
  });

  describe('auto-mark as read', () => {
    it('marks visible notifications as read after 2s delay', async () => {
      vi.useFakeTimers();
      setNotifications([
        createNotification({ notification_id: '1', subject: 'Unread1' }),
        createNotification({ notification_id: '2', subject: 'Unread2' }),
      ]);
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      render(NotificationCenter);
      await user.click(screen.getByRole('button', { name: /Notifications/i }));
      await waitFor(() => { expect(screen.getByText('Unread1')).toBeInTheDocument(); });

      await vi.advanceTimersByTimeAsync(2500);
      expect(mocks.mockNotificationStore.markAsRead).toHaveBeenCalled();
      vi.useRealTimers();
    });
  });

  describe('SSE connection lifecycle', () => {
    it('connects to notification stream when authenticated', async () => {
      mocks.mockIsAuthenticated.set(true);
      render(NotificationCenter);
      await waitFor(() => { expect(MockEventSource.instances.length).toBeGreaterThan(0); });
    });

    it('closes stream and clears store on logout', async () => {
      mocks.mockIsAuthenticated.set(true);
      render(NotificationCenter);
      await waitFor(() => { expect(mocks.mockNotificationStore.load).toHaveBeenCalled(); });

      mocks.mockIsAuthenticated.set(false);
      await waitFor(() => { expect(mocks.mockNotificationStore.clear).toHaveBeenCalled(); });
    });
  });

  describe('SSE message handling', () => {
    it('adds valid notifications to store', async () => {
      const instance = await setupSSE();
      instance.simulateMessage({ notification_id: 'new-1', subject: 'New', body: 'Body' });
      await waitFor(() => { expect(mocks.mockNotificationStore.add).toHaveBeenCalled(); });
    });

    it.each(ignoredSSEMessages)(
      'ignores $desc messages',
      async ({ message, shouldLog }) => {
        const instance = await setupSSE();
        instance.simulateMessage(message);
        expect(mocks.mockNotificationStore.add).not.toHaveBeenCalled();
        if (shouldLog) {
          expect(console.debug).toHaveBeenCalled();
        }
      }
    );

    it('handles JSON parse errors gracefully', async () => {
      const instance = await setupSSE();
      if (instance.onmessage) {
        instance.onmessage(new MessageEvent('message', { data: 'invalid json{' }));
      }
      expect(console.error).toHaveBeenCalled();
    });
  });

  describe('SSE error handling', () => {
    it('attempts reconnection on error', async () => {
      vi.useFakeTimers();
      mocks.mockIsAuthenticated.set(true);
      render(NotificationCenter);
      await vi.waitFor(() => { expect(MockEventSource.instances.length).toBeGreaterThan(0); });

      const instance = MockEventSource.getLastInstance()!;
      await vi.waitFor(() => { expect(instance.onerror).not.toBeNull(); });
      instance.simulateError();

      expect(console.log).toHaveBeenCalled();
      vi.useRealTimers();
    });

    it('closes stream on error when not authenticated', async () => {
      const instance = await setupSSE();
      mocks.mockIsAuthenticated.set(false);
      instance.simulateError();
      expect(instance.readyState).toBe(MockEventSource.CLOSED);
    });

    it('logs error after max reconnection attempts', async () => {
      vi.useFakeTimers();
      mocks.mockIsAuthenticated.set(true);
      render(NotificationCenter);
      await vi.waitFor(() => { expect(MockEventSource.instances.length).toBeGreaterThan(0); });

      for (let i = 0; i < 4; i++) {
        const instance = MockEventSource.getLastInstance()!;
        await vi.waitFor(() => { expect(instance.onerror).not.toBeNull(); });
        instance.simulateError();
        await vi.advanceTimersByTimeAsync(30000);
      }
      expect(console.error).toHaveBeenCalled();
      vi.useRealTimers();
    });

    it('does not reconnect after logout during error', async () => {
      vi.useFakeTimers();
      mocks.mockIsAuthenticated.set(true);
      render(NotificationCenter);
      await vi.waitFor(() => { expect(MockEventSource.instances.length).toBeGreaterThan(0); });
      const initialCount = MockEventSource.instances.length;

      const instance = MockEventSource.getLastInstance()!;
      await vi.waitFor(() => { expect(instance.onerror).not.toBeNull(); });
      mocks.mockIsAuthenticated.set(false);
      instance.simulateError();

      await vi.advanceTimersByTimeAsync(10000);
      expect(MockEventSource.instances.length).toBe(initialCount);
      vi.useRealTimers();
    });
  });
});
