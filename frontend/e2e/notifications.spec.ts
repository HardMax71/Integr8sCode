import { randomUUID } from 'node:crypto';
import { expect, test } from './fixtures';
import { NotificationChannel, NotificationSeverity } from '#lib/api/types.gen.ts';
import { fieldTitle } from '#lib/formatters.ts';

test('the notifications page shows the tag filters', async ({ userPage }) => {
    await userPage.goto('/notifications');
    await expect(userPage.getByRole('heading', { name: 'Notifications', level: 1 })).toBeVisible();
    for (const key of ['include_tags', 'exclude_tags', 'tag_prefix']) {
        await expect(userPage.getByLabel(fieldTitle(key))).toBeVisible();
    }
    await expect(userPage.getByRole('button', { name: 'Filter' })).toBeVisible();
});

test('a filter that matches nothing shows the empty state', async ({ userPage }) => {
    await userPage.goto('/notifications');
    await userPage.getByLabel(fieldTitle('include_tags')).fill(`exec:${randomUUID()}`);
    await userPage.getByRole('button', { name: 'Filter' }).click();
    await expect(userPage.getByText('No notifications yet')).toBeVisible();
});

test('a finished execution arrives as an unread notification', async ({ userPage, execution }) => {
    test.slow();
    await userPage.goto('/notifications');
    const card = userPage.getByRole('article').filter({ hasText: execution.execution_id });
    await expect(card).toBeVisible({ timeout: 20_000 });
    await expect(card.getByText(NotificationChannel.IN_APP, { exact: true })).toBeVisible();
    await expect(card.getByText(new RegExp(`^(${Object.values(NotificationSeverity).join('|')})$`))).toBeVisible();
    await expect(card.getByText(/just now|\d+m ago/)).toBeVisible();
    await expect(card.getByTitle('Mark as read')).toBeVisible();
});

test('a notification can be marked as read and then deleted', async ({ userPage, execution }) => {
    test.slow();
    await userPage.goto('/notifications');
    const card = userPage.getByRole('article').filter({ hasText: execution.execution_id });
    await expect(card).toBeVisible({ timeout: 20_000 });
    await card.getByTitle('Mark as read').click();
    await expect(card.getByTitle('Mark as read')).toHaveCount(0);
    await card.getByRole('button', { name: 'Delete notification' }).click();
    await expect(userPage.getByText('Notification deleted')).toBeVisible();
    await expect(card).toHaveCount(0);
});

test('mark all as read clears every unread notification', async ({ userPage, execution }) => {
    test.slow();
    await userPage.goto('/notifications');
    const card = userPage.getByRole('article').filter({ hasText: execution.execution_id });
    await expect(card).toBeVisible({ timeout: 20_000 });
    await userPage.getByRole('button', { name: 'Mark all as read' }).click();
    await expect(userPage.getByText('All notifications marked as read')).toBeVisible();
    await expect(card.getByTitle('Mark as read')).toHaveCount(0);
});

test('the header shows the notification bell to a signed-in user', async ({ userPage }) => {
    await userPage.goto('/notifications');
    await expect(
        userPage.getByRole('banner').getByRole('button', { name: 'Notifications', exact: true }),
    ).toBeVisible();
});
