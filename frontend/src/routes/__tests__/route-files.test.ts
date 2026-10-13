import { describe, it, expect } from 'vitest';
import { isRedirect } from '@sveltejs/kit';
import { toast } from 'svelte-sonner';
import { fakeUserResponse } from '#lib/api/@faker-js/faker.gen.ts';
import { getCurrentUserProfileApiV1AuthMeGet, UserRole } from '#lib/api/index.ts';
import { mockApi } from '#test/test-utils.ts';
import { load as rootLoad, ssr } from '#routes/+layout.ts';
import { load as authGroupLoad } from '#routes/(auth)/+layout.ts';
import { load as adminLoad } from '#routes/admin/+layout.ts';
import { load as adminIndexLoad } from '#routes/admin/+page.ts';

const url = new URL('https://localhost/editor?tab=1');
const TO_LOGIN = { status: 307, location: '/login?redirect=%2Feditor%3Ftab%3D1' };

describe('route files', () => {
    it('renders every page in the browser only', () => {
        expect(ssr).toBe(false);
    });

    describe('root layout load', () => {
        it('gives every page the signed-in user', async () => {
            const user = fakeUserResponse();
            mockApi(getCurrentUserProfileApiV1AuthMeGet).ok(user);
            await expect(rootLoad({} as Parameters<typeof rootLoad>[0])).resolves.toEqual({ user });
        });

        it.each([
            ['a 401', 401, 'Not authenticated'],
            ['no answer', 0, 'Network error. Check your connection.'],
        ])('gives every page no user after %s, without throwing', async (_label, status, detail) => {
            mockApi(getCurrentUserProfileApiV1AuthMeGet).err({ status, detail });
            await expect(rootLoad({} as Parameters<typeof rootLoad>[0])).resolves.toEqual({ user: null });
        });
    });

    describe('(auth) group guard', () => {
        it('sends a visitor to /login with the page to come back to', async () => {
            const event = { url, parent: () => Promise.resolve({ user: null }) };
            await expect(authGroupLoad(event as Parameters<typeof authGroupLoad>[0])).rejects.toMatchObject(TO_LOGIN);
        });

        it('lets a signed-in user through', async () => {
            const user = fakeUserResponse();
            const event = { url, parent: () => Promise.resolve({ user }) };
            await expect(authGroupLoad(event as Parameters<typeof authGroupLoad>[0])).resolves.toEqual({ user });
        });
    });

    describe('admin guard', () => {
        it('sends a visitor to /login with the page to come back to', async () => {
            const event = { url, parent: () => Promise.resolve({ user: null }) };
            await expect(adminLoad(event as Parameters<typeof adminLoad>[0])).rejects.toMatchObject(TO_LOGIN);
            expect(toast.error).not.toHaveBeenCalled();
        });

        it('sends a signed-in non-admin home with a toast', async () => {
            const event = {
                url,
                parent: () => Promise.resolve({ user: { ...fakeUserResponse(), role: UserRole.USER } }),
            };
            await expect(adminLoad(event as Parameters<typeof adminLoad>[0])).rejects.toMatchObject({
                status: 307,
                location: '/',
            });
            expect(toast.error).toHaveBeenCalledWith('Admin access required');
        });

        it('lets an admin through', async () => {
            const user = { ...fakeUserResponse(), role: UserRole.ADMIN };
            const event = { url, parent: () => Promise.resolve({ user }) };
            await expect(adminLoad(event as Parameters<typeof adminLoad>[0])).resolves.toEqual({ user });
        });
    });

    it('sends /admin to the event browser', () => {
        let thrown: unknown;
        try {
            adminIndexLoad();
        } catch (e) {
            thrown = e;
        }
        expect(isRedirect(thrown) && thrown.location).toBe('/admin/events');
    });
});
