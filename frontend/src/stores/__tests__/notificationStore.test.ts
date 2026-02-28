import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { createMockNotification } from '$test/test-utils';

const mockGetNotifications = vi.fn();
const mockMarkRead = vi.fn();
const mockMarkAllRead = vi.fn();
const mockDeleteNotification = vi.fn();

vi.mock('$lib/api', () => ({
  getNotificationsApiV1NotificationsGet: (...args: unknown[]) => mockGetNotifications(...args),
  markNotificationReadApiV1NotificationsNotificationIdReadPut: (...args: unknown[]) => mockMarkRead(...args),
  markAllReadApiV1NotificationsMarkAllReadPost: (...args: unknown[]) => mockMarkAllRead(...args),
  deleteNotificationApiV1NotificationsNotificationIdDelete: (...args: unknown[]) => mockDeleteNotification(...args),
}));

vi.mock('$lib/api-interceptors', () => ({
  getErrorMessage: (err: unknown, fallback = 'An error occurred') => {
    if (!err) return fallback;
    if (typeof err === 'string') return err;
    if (err instanceof Error) return err.message;
    if (typeof err !== 'object') return fallback;
    const obj = err as Record<string, unknown>;
    if (typeof obj.detail === 'string') return obj.detail;
    if (typeof obj.message === 'string') return obj.message;
    if (Array.isArray(obj.detail)) {
      return (obj.detail as Array<{ loc?: unknown[]; msg?: string }>)
        .map(e => {
          const msg = e.msg ?? String(e);
          if (!e.loc?.length) return msg;
          return `${e.loc[e.loc.length - 1] ?? 'field'}: ${msg}`;
        })
        .join(', ');
    }
    return fallback;
  },
}));

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
      const { notificationStore } = await import('$stores/notificationStore.svelte');
      expect(notificationStore.notifications).toEqual([]);
    });

    it('has loading false', async () => {
      const { notificationStore } = await import('$stores/notificationStore.svelte');
      expect(notificationStore.loading).toBe(false);
    });

    it('has null error', async () => {
      const { notificationStore } = await import('$stores/notificationStore.svelte');
      expect(notificationStore.error).toBe(null);
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

      const { notificationStore } = await import('$stores/notificationStore.svelte');
      const loadPromise = notificationStore.load();

      capturedLoading = notificationStore.loading;
      await loadPromise;

      expect(capturedLoading).toBe(true);
    });

    it('populates notifications on success', async () => {
      const notifications = [
        createMockNotification({ notification_id: 'n1', subject: 'First' }),
        createMockNotification({ notification_id: 'n2', subject: 'Second' }),
      ];
      mockGetNotifications.mockResolvedValue({
        data: { notifications },
        error: null,
      });

      const { notificationStore } = await import('$stores/notificationStore.svelte');
      await notificationStore.load();

      expect(notificationStore.notifications).toHaveLength(2);
      expect(notificationStore.notifications[0]!.subject).toBe('First');
    });

    it('sets loading false after success', async () => {
      mockGetNotifications.mockResolvedValue({
        data: { notifications: [] },
        error: null,
      });

      const { notificationStore } = await import('$stores/notificationStore.svelte');
      await notificationStore.load();

      expect(notificationStore.loading).toBe(false);
    });

    it('returns fetched notifications', async () => {
      const notifications = [createMockNotification()];
      mockGetNotifications.mockResolvedValue({
        data: { notifications },
        error: null,
      });

      const { notificationStore } = await import('$stores/notificationStore.svelte');
      const result = await notificationStore.load();

      expect(result).toEqual(notifications);
    });

    it('sets error on failure', async () => {
      mockGetNotifications.mockResolvedValue({
        data: null,
        error: { detail: [{ msg: 'Failed to fetch' }] },
      });

      const { notificationStore } = await import('$stores/notificationStore.svelte');
      await notificationStore.load();

      expect(notificationStore.error).toBe('Failed to fetch');
    });

    it('returns empty array on failure', async () => {
      mockGetNotifications.mockResolvedValue({
        data: null,
        error: { detail: [{ msg: 'Error' }] },
      });

      const { notificationStore } = await import('$stores/notificationStore.svelte');
      const result = await notificationStore.load();

      expect(result).toEqual([]);
    });

    it('passes limit to API', async () => {
      mockGetNotifications.mockResolvedValue({
        data: { notifications: [] },
        error: null,
      });

      const { notificationStore } = await import('$stores/notificationStore.svelte');
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

      const { notificationStore } = await import('$stores/notificationStore.svelte');
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

      const { notificationStore } = await import('$stores/notificationStore.svelte');
      await notificationStore.load();

      const newNotification = createMockNotification({ notification_id: 'new', subject: 'New' });
      notificationStore.add(newNotification);

      expect(notificationStore.notifications[0]!.notification_id).toBe('new');
      expect(notificationStore.notifications).toHaveLength(2);
    });

  });

  describe('markAsRead', () => {
    it('marks notification as read on success', async () => {
      mockGetNotifications.mockResolvedValue({
        data: {
          notifications: [
            createMockNotification({ notification_id: 'n1', status: 'pending' }),
          ],
        },
        error: null,
      });
      mockMarkRead.mockResolvedValue({ error: null });

      const { notificationStore } = await import('$stores/notificationStore.svelte');
      await notificationStore.load();

      const result = await notificationStore.markAsRead('n1');

      expect(result).toBe(true);
      expect(notificationStore.notifications[0]!.status).toBe('read');
    });

    it('returns false on failure', async () => {
      mockGetNotifications.mockResolvedValue({
        data: { notifications: [createMockNotification({ notification_id: 'n1', status: 'pending' })] },
        error: null,
      });
      mockMarkRead.mockResolvedValue({ error: { detail: 'Failed' } });

      const { notificationStore } = await import('$stores/notificationStore.svelte');
      await notificationStore.load();

      const result = await notificationStore.markAsRead('n1');

      expect(result).toBe(false);
      expect(notificationStore.notifications[0]!.status).toBe('pending');
    });

    it('calls API with correct notification ID', async () => {
      mockMarkRead.mockResolvedValue({ error: null });

      const { notificationStore } = await import('$stores/notificationStore.svelte');
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
            createMockNotification({ notification_id: 'n1', status: 'pending' }),
            createMockNotification({ notification_id: 'n2', status: 'pending' }),
          ],
        },
        error: null,
      });
      mockMarkAllRead.mockResolvedValue({ error: null });

      const { notificationStore } = await import('$stores/notificationStore.svelte');
      await notificationStore.load();

      const result = await notificationStore.markAllAsRead();

      expect(result).toBe(true);
      expect(notificationStore.notifications.every(n => n.status === 'read')).toBe(true);
    });

    it('returns false on failure', async () => {
      mockMarkAllRead.mockResolvedValue({ error: { detail: 'Failed' } });

      const { notificationStore } = await import('$stores/notificationStore.svelte');
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

      const { notificationStore } = await import('$stores/notificationStore.svelte');
      await notificationStore.load();

      const result = await notificationStore.delete('n1');

      expect(result).toBe(true);
      expect(notificationStore.notifications).toHaveLength(1);
      expect(notificationStore.notifications[0]!.notification_id).toBe('n2');
    });

    it('returns false on failure', async () => {
      mockGetNotifications.mockResolvedValue({
        data: { notifications: [createMockNotification({ notification_id: 'n1' })] },
        error: null,
      });
      mockDeleteNotification.mockResolvedValue({ error: { detail: 'Failed' } });

      const { notificationStore } = await import('$stores/notificationStore.svelte');
      await notificationStore.load();

      const result = await notificationStore.delete('n1');

      expect(result).toBe(false);
      expect(notificationStore.notifications).toHaveLength(1);
    });

    it('calls API with correct notification ID', async () => {
      mockDeleteNotification.mockResolvedValue({ error: null });

      const { notificationStore } = await import('$stores/notificationStore.svelte');
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

      const { notificationStore } = await import('$stores/notificationStore.svelte');
      await notificationStore.load();
      expect(notificationStore.notifications).toHaveLength(2);

      notificationStore.clear();

      expect(notificationStore.notifications).toEqual([]);
    });
  });

  describe('refresh', () => {
    it('calls load with default limit', async () => {
      mockGetNotifications.mockResolvedValue({
        data: { notifications: [] },
        error: null,
      });

      const { notificationStore } = await import('$stores/notificationStore.svelte');
      await notificationStore.refresh();

      expect(mockGetNotifications).toHaveBeenCalledWith({
        query: { limit: 20, include_tags: undefined, exclude_tags: undefined, tag_prefix: undefined },
      });
    });
  });

  describe('unreadCount', () => {
    it('counts unread notifications', async () => {
      mockGetNotifications.mockResolvedValue({
        data: {
          notifications: [
            createMockNotification({ notification_id: 'n1', status: 'pending' }),
            createMockNotification({ notification_id: 'n2', status: 'read' }),
            createMockNotification({ notification_id: 'n3', status: 'pending' }),
          ],
          unread_count: 2,
        },
        error: null,
      });

      const { notificationStore } = await import('$stores/notificationStore.svelte');
      await notificationStore.load();

      expect(notificationStore.unreadCount).toBe(2);
    });

    it('returns 0 when all are read', async () => {
      mockGetNotifications.mockResolvedValue({
        data: {
          notifications: [
            createMockNotification({ notification_id: 'n1', status: 'read' }),
          ],
          unread_count: 0,
        },
        error: null,
      });

      const { notificationStore } = await import('$stores/notificationStore.svelte');
      await notificationStore.load();

      expect(notificationStore.unreadCount).toBe(0);
    });

    it('updates when notification is marked as read', async () => {
      mockGetNotifications.mockResolvedValue({
        data: {
          notifications: [
            createMockNotification({ notification_id: 'n1', status: 'pending' }),
          ],
          unread_count: 1,
        },
        error: null,
      });
      mockMarkRead.mockResolvedValue({ error: null });

      const { notificationStore } = await import('$stores/notificationStore.svelte');
      await notificationStore.load();
      expect(notificationStore.unreadCount).toBe(1);

      await notificationStore.markAsRead('n1');
      expect(notificationStore.unreadCount).toBe(0);
    });
  });
});
