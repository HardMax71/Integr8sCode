import { expect, test } from './fixtures';
import { ADMIN_ROUTES } from '#lib/admin/constants.ts';

for (const route of ADMIN_ROUTES) {
    test(`${route.path} shows its heading and marks its link in the admin sidebar`, async ({ adminPage }) => {
        await adminPage.goto(route.path);
        await expect(adminPage.getByRole('heading', { name: route.pageHeading, level: 1 })).toBeVisible();
        await expect(adminPage.getByRole('heading', { name: 'Admin Panel' })).toBeVisible();
        const sidebar = adminPage.getByRole('navigation', { name: 'Admin' });
        for (const link of ADMIN_ROUTES) {
            await expect(sidebar.getByRole('link', { name: link.sidebarLabel, exact: true })).toBeVisible();
        }
        await expect(sidebar.getByRole('link', { name: route.sidebarLabel, exact: true })).toHaveAttribute(
            'aria-current',
            'page',
        );
    });
}
