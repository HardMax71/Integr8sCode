import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { setupAnimationMock, createMockNotification, createMockNotifications } from '$test/test-utils';

const mocks = vi.hoisted(() => ({
  addToast: vi.fn(),
  mockNotificationStore: {
    notifications: [] as ReturnType<typeof createMockNotification>[],
    unreadCount: 0,
    loading: false,
    error: null,
    load: vi.fn(),
    markAsRead: vi.fn(),
    markAllAsRead: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('$stores/notificationStore.svelte', () => ({ notificationStore: mocks.mockNotificationStore }));

vi.mock('svelte-sonner', async () =>
  (await import('$test/test-utils')).createToastMock(mocks.addToast));

vi.mock('$components/Spinner.svelte', async () =>
  (await import('$test/test-utils')).createMockSvelteComponent('<span>Loading</span>', 'spinner'));

vi.mock('@lucide/svelte', async () =>
  (await import('$test/test-utils')).createMockIconModule(
    'Bell', 'Trash2', 'Clock', 'CircleCheck', 'AlertCircle', 'Info'));

vi.mock('$lib/api', () => ({}));

describe('Notifications', () => {
  const user = userEvent.setup();

  beforeEach(() => {
    vi.clearAllMocks();
    setupAnimationMock();
    mocks.mockNotificationStore.notifications = [];
    mocks.mockNotificationStore.unreadCount = 0;
    mocks.mockNotificationStore.loading = false;
    mocks.mockNotificationStore.load.mockResolvedValue([]);
    mocks.mockNotificationStore.markAsRead.mockResolvedValue(true);
    mocks.mockNotificationStore.markAllAsRead.mockResolvedValue(true);
    mocks.mockNotificationStore.delete.mockResolvedValue(true);
  });

  async function renderNotifications() {
    const { default: Notifications } = await import('$routes/Notifications.svelte');
    return render(Notifications);
  }

  it('calls store.load(100) on mount', async () => {
    await renderNotifications();
    await waitFor(() => {
      expect(mocks.mockNotificationStore.load).toHaveBeenCalledWith(100);
    });
  });

  it('shows empty state when no notifications', async () => {
    await renderNotifications();
    await waitFor(() => {
      expect(screen.getByText('No notifications yet')).toBeInTheDocument();
    });
    expect(screen.getByText(/you'll see notifications here/i)).toBeInTheDocument();
  });

  describe('Notification rendering', () => {
    it('renders notification subject, body, channel, severity, and tags', async () => {
      const notif = createMockNotification({
        subject: 'Execution Complete',
        body: 'Your script finished running',
        channel: 'email',
        severity: 'high',
        tags: ['completed', 'exec:abc123'],
        status: 'unread',
      });
      mocks.mockNotificationStore.notifications = [notif as never];
      mocks.mockNotificationStore.unreadCount = 1;

      await renderNotifications();
      await waitFor(() => {
        expect(screen.getByText('Execution Complete')).toBeInTheDocument();
      });
      expect(screen.getByText('Your script finished running')).toBeInTheDocument();
      expect(screen.getByText('email')).toBeInTheDocument();
      expect(screen.getByText('high')).toBeInTheDocument();
      expect(screen.getByText('completed')).toBeInTheDocument();
    });

    it('shows "Read" label for read notifications', async () => {
      mocks.mockNotificationStore.notifications = [createMockNotification({ status: 'read' })] as never[];
      mocks.mockNotificationStore.unreadCount = 0;

      await renderNotifications();
      await waitFor(() => {
        expect(screen.getByText('Read')).toBeInTheDocument();
      });
    });

    it('shows up to 6 tag chips', async () => {
      const tags = ['tag1', 'tag2', 'tag3', 'tag4', 'tag5', 'tag6', 'tag7', 'tag8'];
      mocks.mockNotificationStore.notifications = [createMockNotification({ tags })] as never[];

      await renderNotifications();
      await waitFor(() => {
        expect(screen.getByText('tag1')).toBeInTheDocument();
      });
      expect(screen.getByText('tag6')).toBeInTheDocument();
      expect(screen.queryByText('tag7')).not.toBeInTheDocument();
    });
  });

  describe('Timestamp formatting', () => {
    it.each([
      [0, 'Just now'],
      [3 * 60 * 1000, '3 minutes ago'],
      [5 * 60 * 60 * 1000, '5 hours ago'],
      [2 * 24 * 60 * 60 * 1000, '2 days ago'],
    ])('formats %dms ago as "%s"', async (msAgo, expected) => {
      const date = new Date(Date.now() - msAgo);
      mocks.mockNotificationStore.notifications = [
        createMockNotification({ created_at: date.toISOString() }),
      ] as never[];

      await renderNotifications();
      await waitFor(() => {
        expect(screen.getByText(expected)).toBeInTheDocument();
      });
    });
  });

  describe('Mark as read', () => {
    it('calls markAsRead with exact id when clicking unread notification', async () => {
      mocks.mockNotificationStore.notifications = [
        createMockNotification({ notification_id: 'n-42', status: 'unread' }),
      ] as never[];
      mocks.mockNotificationStore.unreadCount = 1;

      await renderNotifications();
      const card = await waitFor(() =>
        screen.getByRole('button', { name: /mark notification as read/i })
      );
      await user.click(card);
      expect(mocks.mockNotificationStore.markAsRead).toHaveBeenCalledWith('n-42');
    });

    it('does not call markAsRead for already read notifications', async () => {
      mocks.mockNotificationStore.notifications = [
        createMockNotification({ notification_id: 'n-read', status: 'read' }),
      ] as never[];

      await renderNotifications();
      const card = await waitFor(() =>
        screen.getByRole('button', { name: /mark notification as read/i })
      );
      await user.click(card);
      expect(mocks.mockNotificationStore.markAsRead).not.toHaveBeenCalled();
    });
  });

  describe('Mark all as read', () => {
    it('button only visible when unreadCount > 0 and notifications exist', async () => {
      await renderNotifications();
      expect(screen.queryByRole('button', { name: /mark all as read/i })).not.toBeInTheDocument();
    });

    it('calls markAllAsRead and shows success toast', async () => {
      mocks.mockNotificationStore.notifications = createMockNotifications(3) as never[];
      mocks.mockNotificationStore.unreadCount = 2;

      await renderNotifications();
      const btn = await waitFor(() =>
        screen.getByRole('button', { name: /mark all as read/i })
      );
      await user.click(btn);
      expect(mocks.mockNotificationStore.markAllAsRead).toHaveBeenCalled();
      await waitFor(() => {
        expect(mocks.addToast).toHaveBeenCalledWith('success', 'All notifications marked as read');
      });
    });

    it('shows error toast on failure', async () => {
      mocks.mockNotificationStore.markAllAsRead.mockResolvedValue(false);
      mocks.mockNotificationStore.notifications = createMockNotifications(2) as never[];
      mocks.mockNotificationStore.unreadCount = 1;

      await renderNotifications();
      const btn = await waitFor(() =>
        screen.getByRole('button', { name: /mark all as read/i })
      );
      await user.click(btn);
      await waitFor(() => {
        expect(mocks.addToast).toHaveBeenCalledWith('error', 'Failed to mark all as read');
      });
    });
  });

  describe('Delete', () => {
    async function findDeleteButton(): Promise<HTMLElement> {
      const btn = await waitFor(() => {
        const buttons = screen.getAllByRole('button');
        const found = buttons.find(b => b.classList.contains('text-red-600') || b.querySelector('[data-testid="trash-icon"]'));
        expect(found).toBeDefined();
        return found!;
      });
      return btn;
    }

    it('calls delete with exact id and shows success toast', async () => {
      mocks.mockNotificationStore.notifications = [
        createMockNotification({ notification_id: 'del-1' }),
      ] as never[];

      await renderNotifications();
      const deleteBtn = await findDeleteButton();
      await user.click(deleteBtn);
      await waitFor(() => {
        expect(mocks.mockNotificationStore.delete).toHaveBeenCalledWith('del-1');
      });
      expect(mocks.addToast).toHaveBeenCalledWith('success', 'Notification deleted');
    });

    it('shows error toast on delete failure', async () => {
      mocks.mockNotificationStore.delete.mockResolvedValue(false);
      mocks.mockNotificationStore.notifications = [
        createMockNotification({ notification_id: 'del-fail' }),
      ] as never[];

      await renderNotifications();
      const deleteBtn = await findDeleteButton();
      await user.click(deleteBtn);
      await waitFor(() => {
        expect(mocks.addToast).toHaveBeenCalledWith('error', 'Failed to delete notification');
      });
    });

    it('prevents double-click deletion', async () => {
      let resolveDelete: (v: boolean) => void;
      mocks.mockNotificationStore.delete.mockImplementation(
        () => new Promise<boolean>((r) => { resolveDelete = r; })
      );
      mocks.mockNotificationStore.notifications = [
        createMockNotification({ notification_id: 'dbl-1' }),
      ] as never[];

      await renderNotifications();
      const deleteBtn = await findDeleteButton();
      await user.click(deleteBtn);
      await user.click(deleteBtn);
      expect(mocks.mockNotificationStore.delete).toHaveBeenCalledTimes(1);
      resolveDelete!(true);
    });
  });

  describe('Filter', () => {
    it('applies tag filters on button click', async () => {
      await renderNotifications();
      await waitFor(() => {
        expect(screen.getByText('Notifications')).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText('Include tags'), 'exec,completed');
      await user.type(screen.getByLabelText('Exclude tags'), 'alert');
      await user.type(screen.getByLabelText('Tag prefix'), 'exec:');
      await user.click(screen.getByRole('button', { name: 'Filter' }));

      await waitFor(() => {
        expect(mocks.mockNotificationStore.load).toHaveBeenCalledWith(100, {
          include_tags: ['exec', 'completed'],
          exclude_tags: ['alert'],
          tag_prefix: 'exec:',
        });
      });
    });
  });

  describe('View result link', () => {
    it('shows "View result" link for notifications with exec: tag', async () => {
      mocks.mockNotificationStore.notifications = [
        createMockNotification({ tags: ['exec:abc123'] }),
      ] as never[];

      await renderNotifications();
      await waitFor(() => {
        const link = screen.getByRole('link', { name: /view result/i });
        expect(link).toHaveAttribute('href', '/editor?execution=abc123');
      });
    });

    it('does not show "View result" for notifications without exec tag', async () => {
      mocks.mockNotificationStore.notifications = [
        createMockNotification({ tags: ['system', 'info'] }),
      ] as never[];

      await renderNotifications();
      await waitFor(() => {
        expect(screen.getByText('Test Notification')).toBeInTheDocument();
      });
      expect(screen.queryByRole('link', { name: /view result/i })).not.toBeInTheDocument();
    });
  });
});
