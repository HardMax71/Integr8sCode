import type { Request } from '@playwright/test';
import { expect, test } from './fixtures';
import { ADMIN_ROUTES } from '#lib/admin/constants.ts';

/** Whether the page called the admin API, which a guard that runs before the page loads must prevent */
function isAdminApiCall(request: Request): boolean {
    return new URL(request.url()).pathname.startsWith('/api/v1/admin/');
}

for (const path of ['/editor', '/settings', '/notifications']) {
    test(`${path} sends a guest to login and remembers the page`, async ({ page }) => {
        await page.goto(path);
        await expect(page).toHaveURL(`/login?${new URLSearchParams({ redirect: path })}`);
    });
}

for (const { path } of ADMIN_ROUTES) {
    test(`${path} sends a guest to login and remembers the page`, async ({ page }) => {
        await page.goto(path);
        await expect(page).toHaveURL(`/login?${new URLSearchParams({ redirect: path })}`);
    });

    test(`${path} sends a user who is not an admin home before the page asks the admin API`, async ({ userPage }) => {
        await userPage.goto(path);
        await expect(userPage).toHaveURL('/');
        await expect(userPage.getByText('Admin access required')).toBeVisible();
        expect((await userPage.requests()).filter(isAdminApiCall)).toEqual([]);
    });
}
