import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { get } from 'svelte/store';

// Mock the API functions
const mockGetNotifications = vi.fn();
const mockMarkRead = vi.fn();
const mockMarkAllRead = vi.fn();
const mockDeleteNotification = vi.fn();

vi.mock('../../lib/api', () => ({
  getNotificationsApiV1NotificationsGet: (...args: unknown[]) => mockGetNotifications(...args),
  markNotificationReadApiV1NotificationsNotificationIdReadPut: (...args: unknown[]) => mockMarkRead(...args),
  markAllReadApiV1NotificationsMarkAllReadPost: (...args: unknown[]) => mockMarkAllRead(...args),
  deleteNotificationApiV1NotificationsNotificationIdDelete: (...args: unknown[]) => mockDeleteNotification(...args),
}));

const createMockNotification = (overrides = {}) => ({
  notification_id: `notif-${Math.random().toString(36).slice(2)}`,
  title: 'Test Notification',
  message: 'Test message',
  status: 'unread' as const,
  created_at: new Date().toISOString(),
  tags: [],
  ...overrides,
});

describe('notificationStore', () => {
  beforeEach(async () => {
    mockGetNotifications.mockReset();
    mockMarkRead.mockReset();
    mockMarkAllRead.mockReset();
    mockDeleteNotification.mockReset();
    vi.resetModules();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('initial state', () => {
    it('has empty notifications array', async () => {
      const { notificationStore } = await import('../notificationStore');
      expect(get(notificationStore).notifications).toEqual([]);
    });

    it('has loading false', async () => {
      const { notificationStore } = await import('../notificationStore');
      expect(get(notificationStore).loading).toBe(false);
    });

    it('has null error', async () => {
      const { notificationStore } = await import('../notificationStore');
      expect(get(notificationStore).error).toBe(null);
    });
  });

  describe('load', () => {
    it('sets loading true during fetch', async () => {
      let capturedLoading = false;
      mockGetNotifications.mockImplementation(() => {
        return new Promise((resolve) => {
          setTimeout(() => resolve({ data: { notifications: [] }, error: null }), 10);
        });
      });

      const { notificationStore } = await import('../notificationStore');
      const loadPromise = notificationStore.load();

      capturedLoading = get(notificationStore).loading;
      await loadPromise;

      expect(capturedLoading).toBe(true);
    });

    it('populates notifications on success', async () => {
      const notifications = [
        createMockNotification({ notification_id: 'n1', title: 'First' }),
        createMockNotification({ notification_id: 'n2', title: 'Second' }),
      ];
      mockGetNotifications.mockResolvedValue({
        data: { notifications },
        error: null,
      });

      const { notificationStore } = await import('../notificationStore');
      await notificationStore.load();

      expect(get(notificationStore).notifications).toHaveLength(2);
      expect(get(notificationStore).notifications[0].title).toBe('First');
    });

    it('sets loading false after success', async () => {
      mockGetNotifications.mockResolvedValue({
        data: { notifications: [] },
        error: null,
      });

      const { notificationStore } = await import('../notificationStore');
      await notificationStore.load();

      expect(get(notificationStore).loading).toBe(false);
    });

    it('returns fetched notifications', async () => {
      const notifications = [createMockNotification()];
      mockGetNotifications.mockResolvedValue({
        data: { notifications },
        error: null,
      });

      const { notificationStore } = await import('../notificationStore');
      const result = await notificationStore.load();

      expect(result).toEqual(notifications);
    });

    it('sets error on failure', async () => {
      mockGetNotifications.mockResolvedValue({
        data: null,
        error: { detail: [{ msg: 'Failed to fetch' }] },
      });

      const { notificationStore } = await import('../notificationStore');
      await notificationStore.load();

      expect(get(notificationStore).error).toBe('Failed to fetch');
    });

    it('returns empty array on failure', async () => {
      mockGetNotifications.mockResolvedValue({
        data: null,
        error: { detail: [{ msg: 'Error' }] },
      });

      const { notificationStore } = await import('../notificationStore');
      const result = await notificationStore.load();

      expect(result).toEqual([]);
    });

    it('passes limit to API', async () => {
      mockGetNotifications.mockResolvedValue({
        data: { notifications: [] },
        error: null,
      });

      const { notificationStore } = await import('../notificationStore');
      await notificationStore.load(50);

      expect(mockGetNotifications).toHaveBeenCalledWith({
        query: { limit: 50, include_tags: undefined, exclude_tags: undefined, tag_prefix: undefined },
      });
    });

    it('passes tag filters to API', async () => {
      mockGetNotifications.mockResolvedValue({
        data: { notifications: [] },
        error: null,
      });

      const { notificationStore } = await import('../notificationStore');
      await notificationStore.load(20, {
        include_tags: ['important'],
        exclude_tags: ['spam'],
        tag_prefix: 'system:',
      });

      expect(mockGetNotifications).toHaveBeenCalledWith({
        query: {
          limit: 20,
          include_tags: ['important'],
          exclude_tags: ['spam'],
          tag_prefix: 'system:',
        },
      });
    });
  });

  describe('add', () => {
    it('adds notification to the beginning', async () => {
      mockGetNotifications.mockResolvedValue({
        data: { notifications: [createMockNotification({ notification_id: 'existing' })] },
        error: null,
      });

      const { notificationStore } = await import('../notificationStore');
      await notificationStore.load();

      const newNotification = createMockNotification({ notification_id: 'new', title: 'New' });
      notificationStore.add(newNotification);

      const notifications = get(notificationStore).notifications;
      expect(notifications[0].notification_id).toBe('new');
      expect(notifications).toHaveLength(2);
    });

    it('caps notifications at 100', async () => {
      const { notificationStore } = await import('../notificationStore');

      // Add 100 notifications
      for (let i = 0; i < 100; i++) {
        notificationStore.add(createMockNotification({ notification_id: `n${i}` }));
      }

      expect(get(notificationStore).notifications).toHaveLength(100);

      // Add one more
      notificationStore.add(createMockNotification({ notification_id: 'new' }));

      const notifications = get(notificationStore).notifications;
      expect(notifications).toHaveLength(100);
      expect(notifications[0].notification_id).toBe('new');
    });
  });

  describe('markAsRead', () => {
    it('marks notification as read on success', async () => {
      mockGetNotifications.mockResolvedValue({
        data: {
          notifications: [
            createMockNotification({ notification_id: 'n1', status: 'unread' }),
          ],
        },
        error: null,
      });
      mockMarkRead.mockResolvedValue({ error: null });

      const { notificationStore } = await import('../notificationStore');
      await notificationStore.load();

      const result = await notificationStore.markAsRead('n1');

      expect(result).toBe(true);
      expect(get(notificationStore).notifications[0].status).toBe('read');
    });

    it('returns false on failure', async () => {
      mockGetNotifications.mockResolvedValue({
        data: { notifications: [createMockNotification({ notification_id: 'n1' })] },
        error: null,
      });
      mockMarkRead.mockResolvedValue({ error: { detail: 'Failed' } });

      const { notificationStore } = await import('../notificationStore');
      await notificationStore.load();

      const result = await notificationStore.markAsRead('n1');

      expect(result).toBe(false);
      expect(get(notificationStore).notifications[0].status).toBe('unread');
    });

    it('calls API with correct notification ID', async () => {
      mockMarkRead.mockResolvedValue({ error: null });

      const { notificationStore } = await import('../notificationStore');
      await notificationStore.markAsRead('test-id-123');

      expect(mockMarkRead).toHaveBeenCalledWith({
        path: { notification_id: 'test-id-123' },
      });
    });
  });

  describe('markAllAsRead', () => {
    it('marks all notifications as read on success', async () => {
      mockGetNotifications.mockResolvedValue({
        data: {
          notifications: [
            createMockNotification({ notification_id: 'n1', status: 'unread' }),
            createMockNotification({ notification_id: 'n2', status: 'unread' }),
          ],
        },
        error: null,
      });
      mockMarkAllRead.mockResolvedValue({ error: null });

      const { notificationStore } = await import('../notificationStore');
      await notificationStore.load();

      const result = await notificationStore.markAllAsRead();

      expect(result).toBe(true);
      const notifications = get(notificationStore).notifications;
      expect(notifications.every(n => n.status === 'read')).toBe(true);
    });

    it('returns false on failure', async () => {
      mockMarkAllRead.mockResolvedValue({ error: { detail: 'Failed' } });

      const { notificationStore } = await import('../notificationStore');
      const result = await notificationStore.markAllAsRead();

      expect(result).toBe(false);
    });
  });

  describe('delete', () => {
    it('removes notification on success', async () => {
      mockGetNotifications.mockResolvedValue({
        data: {
          notifications: [
            createMockNotification({ notification_id: 'n1' }),
            createMockNotification({ notification_id: 'n2' }),
          ],
        },
        error: null,
      });
      mockDeleteNotification.mockResolvedValue({ error: null });

      const { notificationStore } = await import('../notificationStore');
      await notificationStore.load();

      const result = await notificationStore.delete('n1');

      expect(result).toBe(true);
      const notifications = get(notificationStore).notifications;
      expect(notifications).toHaveLength(1);
      expect(notifications[0].notification_id).toBe('n2');
    });

    it('returns false on failure', async () => {
      mockGetNotifications.mockResolvedValue({
        data: { notifications: [createMockNotification({ notification_id: 'n1' })] },
        error: null,
      });
      mockDeleteNotification.mockResolvedValue({ error: { detail: 'Failed' } });

      const { notificationStore } = await import('../notificationStore');
      await notificationStore.load();

      const result = await notificationStore.delete('n1');

      expect(result).toBe(false);
      expect(get(notificationStore).notifications).toHaveLength(1);
    });

    it('calls API with correct notification ID', async () => {
      mockDeleteNotification.mockResolvedValue({ error: null });

      const { notificationStore } = await import('../notificationStore');
      await notificationStore.delete('delete-me-123');

      expect(mockDeleteNotification).toHaveBeenCalledWith({
        path: { notification_id: 'delete-me-123' },
      });
    });
  });

  describe('clear', () => {
    it('clears all notifications', async () => {
      mockGetNotifications.mockResolvedValue({
        data: {
          notifications: [
            createMockNotification(),
            createMockNotification(),
          ],
        },
        error: null,
      });

      const { notificationStore } = await import('../notificationStore');
      await notificationStore.load();
      expect(get(notificationStore).notifications).toHaveLength(2);

      notificationStore.clear();

      expect(get(notificationStore).notifications).toEqual([]);
    });
  });

  describe('refresh', () => {
    it('calls load with default limit', async () => {
      mockGetNotifications.mockResolvedValue({
        data: { notifications: [] },
        error: null,
      });

      const { notificationStore } = await import('../notificationStore');
      await notificationStore.refresh();

      expect(mockGetNotifications).toHaveBeenCalledWith({
        query: { limit: 20, include_tags: undefined, exclude_tags: undefined, tag_prefix: undefined },
      });
    });
  });

  describe('unreadCount derived store', () => {
    it('counts unread notifications', async () => {
      mockGetNotifications.mockResolvedValue({
        data: {
          notifications: [
            createMockNotification({ notification_id: 'n1', status: 'unread' }),
            createMockNotification({ notification_id: 'n2', status: 'read' }),
            createMockNotification({ notification_id: 'n3', status: 'unread' }),
          ],
        },
        error: null,
      });

      const { notificationStore, unreadCount } = await import('../notificationStore');
      await notificationStore.load();

      expect(get(unreadCount)).toBe(2);
    });

    it('returns 0 when all are read', async () => {
      mockGetNotifications.mockResolvedValue({
        data: {
          notifications: [
            createMockNotification({ notification_id: 'n1', status: 'read' }),
          ],
        },
        error: null,
      });

      const { notificationStore, unreadCount } = await import('../notificationStore');
      await notificationStore.load();

      expect(get(unreadCount)).toBe(0);
    });

    it('updates when notification is marked as read', async () => {
      mockGetNotifications.mockResolvedValue({
        data: {
          notifications: [
            createMockNotification({ notification_id: 'n1', status: 'unread' }),
          ],
        },
        error: null,
      });
      mockMarkRead.mockResolvedValue({ error: null });

      const { notificationStore, unreadCount } = await import('../notificationStore');
      await notificationStore.load();
      expect(get(unreadCount)).toBe(1);

      await notificationStore.markAsRead('n1');
      expect(get(unreadCount)).toBe(0);
    });
  });

  describe('notifications derived store', () => {
    it('exposes notifications array', async () => {
      const notifs = [
        createMockNotification({ notification_id: 'n1', title: 'First' }),
        createMockNotification({ notification_id: 'n2', title: 'Second' }),
      ];
      mockGetNotifications.mockResolvedValue({
        data: { notifications: notifs },
        error: null,
      });

      const { notificationStore, notifications } = await import('../notificationStore');
      await notificationStore.load();

      expect(get(notifications)).toHaveLength(2);
      expect(get(notifications)[0].title).toBe('First');
    });
  });
});
