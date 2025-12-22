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

// Mock EventSource
class MockEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  readyState = MockEventSource.OPEN;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  constructor(public url: string, public options?: { withCredentials?: boolean }) {
    setTimeout(() => { if (this.onopen) this.onopen(new Event('open')); }, 0);
  }
  close() { this.readyState = MockEventSource.CLOSED; }
}
vi.stubGlobal('EventSource', MockEventSource);
vi.stubGlobal('Notification', { permission: 'default', requestPermission: vi.fn().mockResolvedValue('granted') });

import NotificationCenter from '../NotificationCenter.svelte';

// Test helpers
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
  const button = screen.getByRole('button', { name: /Notifications/i });
  await user.click(button);
  return user;
};

const openDropdownWithContainer = async () => {
  const user = userEvent.setup();
  const { container } = render(NotificationCenter);
  const button = screen.getByRole('button', { name: /Notifications/i });
  await user.click(button);
  return { user, container };
};

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
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.spyOn(console, 'debug').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => { vi.restoreAllMocks(); });

  describe('bell icon', () => {
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

    it.each([
      { count: 2, expected: '2' },
      { count: 9, expected: '9' },
      { count: 12, expected: '9+' },
    ])('shows badge "$expected" when $count unread notifications', async ({ count, expected }) => {
      const notifications = Array.from({ length: count }, (_, i) =>
        createNotification({ notification_id: String(i), subject: `Test ${i}` })
      );
      setNotifications(notifications);
      const { container } = render(NotificationCenter);

      await waitFor(() => {
        const badge = container.querySelector('.bg-red-500');
        expect(badge?.textContent).toBe(expected);
      });
    });
  });

  describe('dropdown', () => {
    it('opens dropdown when bell clicked', async () => {
      await openDropdown();
      await waitFor(() => { expect(screen.getByText('Notifications')).toBeInTheDocument(); });
    });

    it('shows empty state when no notifications', async () => {
      await openDropdown();
      await waitFor(() => { expect(screen.getByText('No notifications yet')).toBeInTheDocument(); });
    });

    it('shows View all notifications link', async () => {
      await openDropdown();
      await waitFor(() => { expect(screen.getByText('View all notifications')).toBeInTheDocument(); });
    });

    it('navigates and closes when View all clicked', async () => {
      const user = await openDropdown();
      await waitFor(() => { expect(screen.getByText('View all notifications')).toBeInTheDocument(); });
      await user.click(screen.getByText('View all notifications'));
      await waitFor(() => { expect(screen.queryByText('No notifications yet')).not.toBeInTheDocument(); });
      expect(mocks.mockGoto).toHaveBeenCalledWith('/notifications');
    });
  });

  describe('notification list', () => {
    const sampleNotifications: MockNotification[] = [
      createNotification({ notification_id: '1', subject: 'Build Completed', body: 'Your build finished successfully', tags: ['completed', 'success'], action_url: '/builds/123' }),
      createNotification({ notification_id: '2', subject: 'Build Failed', body: 'Build encountered an error', status: 'read', severity: 'high', tags: ['failed', 'error'], created_at: new Date(Date.now() - 3600000).toISOString() }),
    ];

    beforeEach(() => { setNotifications(sampleNotifications); });

    it('displays notification subjects and bodies', async () => {
      await openDropdown();
      await waitFor(() => {
        expect(screen.getByText('Build Completed')).toBeInTheDocument();
        expect(screen.getByText('Build Failed')).toBeInTheDocument();
        expect(screen.getByText('Your build finished successfully')).toBeInTheDocument();
        expect(screen.getByText('Build encountered an error')).toBeInTheDocument();
      });
    });

    it('shows unread indicator and background for unread notifications', async () => {
      const { container } = await openDropdownWithContainer();
      await waitFor(() => {
        expect(container.querySelectorAll('.bg-blue-500.rounded-full').length).toBeGreaterThan(0);
        expect(container.querySelector('.bg-blue-50')).toBeInTheDocument();
      });
    });
  });

  describe('mark as read', () => {
    it.each([
      { status: 'unread' as const, shouldShow: true, verb: 'shows' },
      { status: 'read' as const, shouldShow: false, verb: 'hides' },
    ])('$verb Mark all as read when notifications are $status', async ({ status, shouldShow }) => {
      setNotifications([createNotification({ status })]);
      await openDropdown();
      await waitFor(() => {
        if (shouldShow) {
          expect(screen.getByText('Mark all as read')).toBeInTheDocument();
        } else {
          expect(screen.queryByText('Mark all as read')).not.toBeInTheDocument();
        }
      });
    });

    it('calls markAllAsRead when button clicked', async () => {
      setNotifications([createNotification()]);
      const user = await openDropdown();
      await waitFor(() => { expect(screen.getByText('Mark all as read')).toBeInTheDocument(); });
      await user.click(screen.getByText('Mark all as read'));
      expect(mocks.mockNotificationStore.markAllAsRead).toHaveBeenCalled();
    });
  });

  describe('notification icons', () => {
    it.each([
      { tags: ['completed'], subject: 'Success', svgPath: 'M9 12l2 2 4-4' },
      { tags: ['failed'], subject: 'Error', svgPath: 'M12 8v4m0 4h.01' },
      { tags: ['timeout'], subject: 'Warning', svgPath: 'M12 9v2m0 4h.01' },
    ])('shows correct icon for $tags tags', async ({ tags, subject, svgPath }) => {
      setNotifications([createNotification({ tags, subject })]);
      const { container } = await openDropdownWithContainer();
      await waitFor(() => {
        const notificationItem = container.querySelector(`[role="button"][aria-label*="${subject}"]`);
        expect(notificationItem?.querySelector('svg')?.innerHTML).toContain(svgPath);
      });
    });
  });

  describe('priority colors', () => {
    it.each([
      { severity: 'high' as const, colorClass: '.text-orange-600' },
      { severity: 'urgent' as const, colorClass: '.text-red-600' },
    ])('applies $colorClass for $severity priority', async ({ severity, colorClass }) => {
      setNotifications([createNotification({ severity, subject: severity })]);
      const { container } = await openDropdownWithContainer();
      await waitFor(() => { expect(container.querySelector(colorClass)).toBeInTheDocument(); });
    });
  });

  describe('time formatting', () => {
    it.each([
      { offsetMs: 0, expected: 'just now' },
      { offsetMs: 5 * 60 * 1000, expected: '5m ago' },
      { offsetMs: 3 * 60 * 60 * 1000, expected: '3h ago' },
    ])('shows "$expected" for notifications $offsetMs ms ago', async ({ offsetMs, expected }) => {
      setNotifications([createNotification({ created_at: new Date(Date.now() - offsetMs).toISOString() })]);
      await openDropdown();
      await waitFor(() => { expect(screen.getByText(expected)).toBeInTheDocument(); });
    });
  });

  describe('notification click', () => {
    it('marks notification as read when clicked', async () => {
      setNotifications([createNotification({ subject: 'Clickable' })]);
      const user = await openDropdown();
      await waitFor(() => { expect(screen.getByText('Clickable')).toBeInTheDocument(); });
      await user.click(screen.getByRole('button', { name: /View notification: Clickable/i }));
      expect(mocks.mockNotificationStore.markAsRead).toHaveBeenCalledWith('1');
    });

    it('navigates to action_url for internal links', async () => {
      setNotifications([createNotification({ subject: 'Internal', action_url: '/builds/123' })]);
      const user = await openDropdown();
      await waitFor(() => { expect(screen.getByText('Internal')).toBeInTheDocument(); });
      await user.click(screen.getByRole('button', { name: /View notification: Internal/i }));
      expect(mocks.mockGoto).toHaveBeenCalledWith('/builds/123');
    });

    it('handles keyboard navigation with Enter key', async () => {
      setNotifications([createNotification({ subject: 'Keyboard', action_url: '/test' })]);
      const user = await openDropdown();
      await waitFor(() => { expect(screen.getByText('Keyboard')).toBeInTheDocument(); });
      screen.getByRole('button', { name: /View notification: Keyboard/i }).focus();
      await user.keyboard('{Enter}');
      expect(mocks.mockNotificationStore.markAsRead).toHaveBeenCalledWith('1');
      expect(mocks.mockGoto).toHaveBeenCalledWith('/test');
    });
  });

  describe('accessibility', () => {
    it('has aria-label on notification button', () => {
      render(NotificationCenter);
      expect(screen.getByRole('button', { name: /Notifications/i }).getAttribute('aria-label')).toBe('Notifications');
    });

    it('notification items have proper aria-label and are focusable', async () => {
      setNotifications([createNotification({ subject: 'Test Subject' })]);
      await openDropdown();
      await waitFor(() => {
        const notificationItem = screen.getByRole('button', { name: /View notification: Test Subject/i });
        expect(notificationItem).toBeInTheDocument();
        expect(notificationItem.getAttribute('tabindex')).toBe('0');
      });
    });
  });
});
