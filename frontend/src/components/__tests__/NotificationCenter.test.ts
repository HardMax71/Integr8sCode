import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { tick, flushSync } from 'svelte';

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

interface NotificationsState {
  notifications: MockNotification[];
  loading: boolean;
  error: string | null;
}

// Use vi.hoisted to create hoisted mock variables
const mocks = vi.hoisted(() => {
  // Create a simple mock store factory
  function createMockStore<T>(initial: T) {
    let value = initial;
    const subscribers = new Set<(v: T) => void>();

    return {
      set(v: T) {
        value = v;
        subscribers.forEach(fn => fn(v));
      },
      subscribe(fn: (v: T) => void) {
        fn(value);
        subscribers.add(fn);
        return () => subscribers.delete(fn);
      },
      update(fn: (v: T) => T) {
        this.set(fn(value));
      },
      _getValue() {
        return value;
      },
    };
  }

  // Create a derived-like store
  function createDerivedStore<T, R>(
    source: { subscribe: (fn: (v: T) => void) => () => void; _getValue: () => T },
    fn: (v: T) => R
  ) {
    const subscribers = new Set<(v: R) => void>();
    let currentValue = fn(source._getValue());

    source.subscribe((v) => {
      currentValue = fn(v);
      subscribers.forEach(sub => sub(currentValue));
    });

    return {
      subscribe(callback: (v: R) => void) {
        callback(currentValue);
        subscribers.add(callback);
        return () => subscribers.delete(callback);
      },
    };
  }

  interface MockNotificationState {
    notifications: Array<{
      notification_id: string;
      subject: string;
      body: string;
      status: 'unread' | 'read';
      severity: 'low' | 'medium' | 'high' | 'urgent';
      tags: string[];
      created_at: string;
      action_url?: string;
    }>;
    loading: boolean;
    error: string | null;
  }

  const mockIsAuthenticated = createMockStore<boolean | null>(true);
  const mockUsername = createMockStore<string | null>('testuser');
  const mockUserId = createMockStore<string | null>('user-123');
  const mockNotificationsState = createMockStore<MockNotificationState>({
    notifications: [],
    loading: false,
    error: null,
  });

  const mockNotifications = createDerivedStore(mockNotificationsState, s => s.notifications);
  const mockUnreadCount = createDerivedStore(mockNotificationsState, s =>
    s.notifications.filter(n => n.status !== 'read').length
  );

  return {
    mockIsAuthenticated,
    mockUsername,
    mockUserId,
    mockNotificationsState,
    mockNotifications,
    mockUnreadCount,
    mockGoto: (null as unknown) as ReturnType<typeof import('vitest').vi.fn>,
    mockNotificationStore: (null as unknown) as {
      subscribe: typeof mockNotificationsState.subscribe;
      load: ReturnType<typeof import('vitest').vi.fn>;
      add: ReturnType<typeof import('vitest').vi.fn>;
      markAsRead: ReturnType<typeof import('vitest').vi.fn>;
      markAllAsRead: ReturnType<typeof import('vitest').vi.fn>;
      delete: ReturnType<typeof import('vitest').vi.fn>;
      clear: ReturnType<typeof import('vitest').vi.fn>;
      refresh: ReturnType<typeof import('vitest').vi.fn>;
    },
  };
});

// Initialize mocks that need vi.fn() outside of hoisted context
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

// Mock router - use getter to defer access
vi.mock('@mateothegreat/svelte5-router', () => ({
  get goto() { return (...args: unknown[]) => mocks.mockGoto(...args); },
}));

// Mock auth store - use getters to defer access
vi.mock('../../stores/auth', () => ({
  get isAuthenticated() { return mocks.mockIsAuthenticated; },
  get username() { return mocks.mockUsername; },
  get userId() { return mocks.mockUserId; },
}));

// Mock notification store - use getters to defer access
vi.mock('../../stores/notificationStore', () => ({
  get notificationStore() { return mocks.mockNotificationStore; },
  get notifications() { return mocks.mockNotifications; },
  get unreadCount() { return mocks.mockUnreadCount; },
}));

// Animation mock factory for Svelte transitions
const createAnimationMock = () => ({
  _onfinish: null as (() => void) | null,
  get onfinish() { return this._onfinish; },
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
    return Promise.resolve(this);
  },
  get ready() {
    return Promise.resolve(this);
  },
  oncancel: null,
  onremove: null,
});

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
    setTimeout(() => {
      if (this.onopen) {
        this.onopen(new Event('open'));
      }
    }, 0);
  }

  close() {
    this.readyState = MockEventSource.CLOSED;
  }
}

vi.stubGlobal('EventSource', MockEventSource);

// Mock Notification API
vi.stubGlobal('Notification', {
  permission: 'default',
  requestPermission: vi.fn().mockResolvedValue('granted'),
});

import NotificationCenter from '../NotificationCenter.svelte';

describe('NotificationCenter', () => {
  beforeEach(() => {
    // Mock Element.prototype.animate for Svelte transitions
    Element.prototype.animate = vi.fn().mockImplementation(() => createAnimationMock());

    // Reset stores
    mocks.mockIsAuthenticated.set(true);
    mocks.mockUsername.set('testuser');
    mocks.mockUserId.set('user-123');
    mocks.mockNotificationsState.set({
      notifications: [],
      loading: false,
      error: null,
    });

    // Reset mocks
    mocks.mockGoto.mockReset();
    mocks.mockNotificationStore.load.mockReset().mockResolvedValue([]);
    mocks.mockNotificationStore.markAsRead.mockReset().mockResolvedValue(true);
    mocks.mockNotificationStore.markAllAsRead.mockReset().mockResolvedValue(true);
    mocks.mockNotificationStore.clear.mockReset();
    mocks.mockNotificationStore.add.mockReset();

    // Suppress console output
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.spyOn(console, 'debug').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('bell icon', () => {
    it('renders notification button with bell icon', () => {
      render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      expect(button).toBeInTheDocument();

      const svg = button.querySelector('svg');
      expect(svg).toBeInTheDocument();
    });

    it('shows no badge when no unread notifications', () => {
      mocks.mockNotificationsState.set({
        notifications: [],
        loading: false,
        error: null,
      });

      const { container } = render(NotificationCenter);

      const badge = container.querySelector('.bg-red-500');
      expect(badge).not.toBeInTheDocument();
    });

    it('shows unread count badge', async () => {
      mocks.mockNotificationsState.set({
        notifications: [
          { notification_id: '1', subject: 'Test', body: 'Body', status: 'unread', severity: 'medium', tags: [], created_at: new Date().toISOString() },
          { notification_id: '2', subject: 'Test 2', body: 'Body 2', status: 'unread', severity: 'medium', tags: [], created_at: new Date().toISOString() },
        ],
        loading: false,
        error: null,
      });

      const { container } = render(NotificationCenter);

      await waitFor(() => {
        const badge = container.querySelector('.bg-red-500');
        expect(badge).toBeInTheDocument();
        expect(badge?.textContent).toBe('2');
      });
    });

    it('shows 9+ when more than 9 unread', async () => {
      const notifications = Array.from({ length: 12 }, (_, i) => ({
        notification_id: String(i),
        subject: `Test ${i}`,
        body: `Body ${i}`,
        status: 'unread' as const,
        severity: 'medium' as const,
        tags: [],
        created_at: new Date().toISOString(),
      }));

      mocks.mockNotificationsState.set({
        notifications,
        loading: false,
        error: null,
      });

      const { container } = render(NotificationCenter);

      await waitFor(() => {
        const badge = container.querySelector('.bg-red-500');
        expect(badge?.textContent).toBe('9+');
      });
    });
  });

  describe('dropdown', () => {
    it('opens dropdown when bell clicked', async () => {
      const user = userEvent.setup();
      render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        expect(screen.getByText('Notifications')).toBeInTheDocument();
      });
    });

    it('closes dropdown when View all notifications clicked', async () => {
      const user = userEvent.setup();
      render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });

      // First click opens dropdown
      await user.click(button);

      await waitFor(() => {
        expect(screen.getByText('Notifications')).toBeInTheDocument();
        expect(screen.getByText('View all notifications')).toBeInTheDocument();
      });

      // Click "View all notifications" which closes dropdown via onclick
      const viewAllButton = screen.getByText('View all notifications');
      await user.click(viewAllButton);

      // After clicking View all, dropdown should close and navigate
      await waitFor(() => {
        expect(screen.queryByText('No notifications yet')).not.toBeInTheDocument();
      });

      expect(mocks.mockGoto).toHaveBeenCalledWith('/notifications');
    });

    it('shows empty state when no notifications', async () => {
      const user = userEvent.setup();
      render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        expect(screen.getByText('No notifications yet')).toBeInTheDocument();
      });
    });

    it('shows View all notifications link', async () => {
      const user = userEvent.setup();
      render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        expect(screen.getByText('View all notifications')).toBeInTheDocument();
      });
    });

    it('navigates to notifications page when View all clicked', async () => {
      const user = userEvent.setup();
      render(NotificationCenter);

      const bellButton = screen.getByRole('button', { name: /Notifications/i });
      await user.click(bellButton);

      await waitFor(() => {
        expect(screen.getByText('View all notifications')).toBeInTheDocument();
      });

      const viewAllButton = screen.getByText('View all notifications');
      await user.click(viewAllButton);

      expect(mocks.mockGoto).toHaveBeenCalledWith('/notifications');
    });
  });

  describe('notification list', () => {
    const sampleNotifications: MockNotification[] = [
      {
        notification_id: '1',
        subject: 'Build Completed',
        body: 'Your build finished successfully',
        status: 'unread',
        severity: 'medium',
        tags: ['completed', 'success'],
        created_at: new Date().toISOString(),
        action_url: '/builds/123',
      },
      {
        notification_id: '2',
        subject: 'Build Failed',
        body: 'Build encountered an error',
        status: 'read',
        severity: 'high',
        tags: ['failed', 'error'],
        created_at: new Date(Date.now() - 3600000).toISOString(),
      },
    ];

    beforeEach(() => {
      mocks.mockNotificationsState.set({
        notifications: sampleNotifications,
        loading: false,
        error: null,
      });
    });

    it('displays notification subjects', async () => {
      const user = userEvent.setup();
      render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        expect(screen.getByText('Build Completed')).toBeInTheDocument();
        expect(screen.getByText('Build Failed')).toBeInTheDocument();
      });
    });

    it('displays notification bodies', async () => {
      const user = userEvent.setup();
      render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        expect(screen.getByText('Your build finished successfully')).toBeInTheDocument();
        expect(screen.getByText('Build encountered an error')).toBeInTheDocument();
      });
    });

    it('shows unread indicator for unread notifications', async () => {
      const user = userEvent.setup();
      const { container } = render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        const unreadDots = container.querySelectorAll('.bg-blue-500.rounded-full');
        expect(unreadDots.length).toBeGreaterThan(0);
      });
    });

    it('applies different background for unread notifications', async () => {
      const user = userEvent.setup();
      const { container } = render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        const unreadItem = container.querySelector('.bg-blue-50');
        expect(unreadItem).toBeInTheDocument();
      });
    });
  });

  describe('mark as read', () => {
    it('shows Mark all as read button when there are unread notifications', async () => {
      mocks.mockNotificationsState.set({
        notifications: [
          { notification_id: '1', subject: 'Test', body: 'Body', status: 'unread', severity: 'medium', tags: [], created_at: new Date().toISOString() },
        ],
        loading: false,
        error: null,
      });

      const user = userEvent.setup();
      render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        expect(screen.getByText('Mark all as read')).toBeInTheDocument();
      });
    });

    it('hides Mark all as read when all are read', async () => {
      mocks.mockNotificationsState.set({
        notifications: [
          { notification_id: '1', subject: 'Test', body: 'Body', status: 'read', severity: 'medium', tags: [], created_at: new Date().toISOString() },
        ],
        loading: false,
        error: null,
      });

      const user = userEvent.setup();
      render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        expect(screen.queryByText('Mark all as read')).not.toBeInTheDocument();
      });
    });

    it('calls markAllAsRead when button clicked', async () => {
      mocks.mockNotificationsState.set({
        notifications: [
          { notification_id: '1', subject: 'Test', body: 'Body', status: 'unread', severity: 'medium', tags: [], created_at: new Date().toISOString() },
        ],
        loading: false,
        error: null,
      });

      const user = userEvent.setup();
      render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        expect(screen.getByText('Mark all as read')).toBeInTheDocument();
      });

      const markAllButton = screen.getByText('Mark all as read');
      await user.click(markAllButton);

      expect(mocks.mockNotificationStore.markAllAsRead).toHaveBeenCalled();
    });
  });

  describe('notification icons', () => {
    it('shows success icon for completed/success tags', async () => {
      mocks.mockNotificationsState.set({
        notifications: [
          { notification_id: '1', subject: 'Success', body: 'Body', status: 'unread', severity: 'medium', tags: ['completed'], created_at: new Date().toISOString() },
        ],
        loading: false,
        error: null,
      });

      const user = userEvent.setup();
      const { container } = render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        const notificationItem = container.querySelector('[role="button"][aria-label*="Success"]');
        const svg = notificationItem?.querySelector('svg');
        expect(svg?.innerHTML).toContain('M9 12l2 2 4-4');
      });
    });

    it('shows error icon for failed/error tags', async () => {
      mocks.mockNotificationsState.set({
        notifications: [
          { notification_id: '1', subject: 'Error', body: 'Body', status: 'unread', severity: 'high', tags: ['failed'], created_at: new Date().toISOString() },
        ],
        loading: false,
        error: null,
      });

      const user = userEvent.setup();
      const { container } = render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        const notificationItem = container.querySelector('[role="button"][aria-label*="Error"]');
        const svg = notificationItem?.querySelector('svg');
        expect(svg?.innerHTML).toContain('M12 8v4m0 4h.01');
      });
    });

    it('shows warning icon for timeout/warning tags', async () => {
      mocks.mockNotificationsState.set({
        notifications: [
          { notification_id: '1', subject: 'Warning', body: 'Body', status: 'unread', severity: 'medium', tags: ['timeout'], created_at: new Date().toISOString() },
        ],
        loading: false,
        error: null,
      });

      const user = userEvent.setup();
      const { container } = render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        const notificationItem = container.querySelector('[role="button"][aria-label*="Warning"]');
        const svg = notificationItem?.querySelector('svg');
        expect(svg?.innerHTML).toContain('M12 9v2m0 4h.01');
      });
    });
  });

  describe('priority colors', () => {
    it('applies correct color for high priority', async () => {
      mocks.mockNotificationsState.set({
        notifications: [
          { notification_id: '1', subject: 'High', body: 'Body', status: 'unread', severity: 'high', tags: [], created_at: new Date().toISOString() },
        ],
        loading: false,
        error: null,
      });

      const user = userEvent.setup();
      const { container } = render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        const iconWrapper = container.querySelector('.text-orange-600');
        expect(iconWrapper).toBeInTheDocument();
      });
    });

    it('applies correct color for urgent priority', async () => {
      mocks.mockNotificationsState.set({
        notifications: [
          { notification_id: '1', subject: 'Urgent', body: 'Body', status: 'unread', severity: 'urgent', tags: [], created_at: new Date().toISOString() },
        ],
        loading: false,
        error: null,
      });

      const user = userEvent.setup();
      const { container } = render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        const iconWrapper = container.querySelector('.text-red-600');
        expect(iconWrapper).toBeInTheDocument();
      });
    });
  });

  describe('time formatting', () => {
    it('shows "just now" for recent notifications', async () => {
      mocks.mockNotificationsState.set({
        notifications: [
          { notification_id: '1', subject: 'Recent', body: 'Body', status: 'unread', severity: 'medium', tags: [], created_at: new Date().toISOString() },
        ],
        loading: false,
        error: null,
      });

      const user = userEvent.setup();
      render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        expect(screen.getByText('just now')).toBeInTheDocument();
      });
    });

    it('shows minutes ago for recent notifications', async () => {
      const fiveMinutesAgo = new Date(Date.now() - 5 * 60 * 1000);
      mocks.mockNotificationsState.set({
        notifications: [
          { notification_id: '1', subject: 'Minutes', body: 'Body', status: 'unread', severity: 'medium', tags: [], created_at: fiveMinutesAgo.toISOString() },
        ],
        loading: false,
        error: null,
      });

      const user = userEvent.setup();
      render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        expect(screen.getByText('5m ago')).toBeInTheDocument();
      });
    });

    it('shows hours ago for older notifications', async () => {
      const threeHoursAgo = new Date(Date.now() - 3 * 60 * 60 * 1000);
      mocks.mockNotificationsState.set({
        notifications: [
          { notification_id: '1', subject: 'Hours', body: 'Body', status: 'unread', severity: 'medium', tags: [], created_at: threeHoursAgo.toISOString() },
        ],
        loading: false,
        error: null,
      });

      const user = userEvent.setup();
      render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        expect(screen.getByText('3h ago')).toBeInTheDocument();
      });
    });
  });

  describe('notification click', () => {
    it('marks notification as read when clicked', async () => {
      mocks.mockNotificationsState.set({
        notifications: [
          { notification_id: '1', subject: 'Clickable', body: 'Body', status: 'unread', severity: 'medium', tags: [], created_at: new Date().toISOString() },
        ],
        loading: false,
        error: null,
      });

      const user = userEvent.setup();
      render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        expect(screen.getByText('Clickable')).toBeInTheDocument();
      });

      const notificationItem = screen.getByRole('button', { name: /View notification: Clickable/i });
      await user.click(notificationItem);

      expect(mocks.mockNotificationStore.markAsRead).toHaveBeenCalledWith('1');
    });

    it('navigates to action_url for internal links', async () => {
      mocks.mockNotificationsState.set({
        notifications: [
          { notification_id: '1', subject: 'Internal', body: 'Body', status: 'unread', severity: 'medium', tags: [], created_at: new Date().toISOString(), action_url: '/builds/123' },
        ],
        loading: false,
        error: null,
      });

      const user = userEvent.setup();
      render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        expect(screen.getByText('Internal')).toBeInTheDocument();
      });

      const notificationItem = screen.getByRole('button', { name: /View notification: Internal/i });
      await user.click(notificationItem);

      expect(mocks.mockGoto).toHaveBeenCalledWith('/builds/123');
    });

    it('handles keyboard navigation with Enter key', async () => {
      mocks.mockNotificationsState.set({
        notifications: [
          { notification_id: '1', subject: 'Keyboard', body: 'Body', status: 'unread', severity: 'medium', tags: [], created_at: new Date().toISOString(), action_url: '/test' },
        ],
        loading: false,
        error: null,
      });

      const user = userEvent.setup();
      render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        expect(screen.getByText('Keyboard')).toBeInTheDocument();
      });

      const notificationItem = screen.getByRole('button', { name: /View notification: Keyboard/i });
      notificationItem.focus();
      await user.keyboard('{Enter}');

      expect(mocks.mockNotificationStore.markAsRead).toHaveBeenCalledWith('1');
      expect(mocks.mockGoto).toHaveBeenCalledWith('/test');
    });
  });

  describe('accessibility', () => {
    it('has aria-label on notification button', () => {
      render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      expect(button.getAttribute('aria-label')).toBe('Notifications');
    });

    it('notification items have proper aria-label', async () => {
      mocks.mockNotificationsState.set({
        notifications: [
          { notification_id: '1', subject: 'Test Subject', body: 'Body', status: 'unread', severity: 'medium', tags: [], created_at: new Date().toISOString() },
        ],
        loading: false,
        error: null,
      });

      const user = userEvent.setup();
      render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        const notificationItem = screen.getByRole('button', { name: /View notification: Test Subject/i });
        expect(notificationItem).toBeInTheDocument();
      });
    });

    it('notification items are focusable', async () => {
      mocks.mockNotificationsState.set({
        notifications: [
          { notification_id: '1', subject: 'Focusable', body: 'Body', status: 'unread', severity: 'medium', tags: [], created_at: new Date().toISOString() },
        ],
        loading: false,
        error: null,
      });

      const user = userEvent.setup();
      render(NotificationCenter);

      const button = screen.getByRole('button', { name: /Notifications/i });
      await user.click(button);

      await waitFor(() => {
        const notificationItem = screen.getByRole('button', { name: /View notification: Focusable/i });
        expect(notificationItem.getAttribute('tabindex')).toBe('0');
      });
    });
  });
});
