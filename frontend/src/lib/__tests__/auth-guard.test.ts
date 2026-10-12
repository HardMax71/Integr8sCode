import { describe, it, expect, beforeEach, vi } from 'vitest';
import { isRedirect } from '@sveltejs/kit';
import { toast } from 'svelte-sonner';
import { requireAdmin, requireAuth } from '#lib/auth-guard.ts';
import { fakeUserResponse } from '#lib/api/@faker-js/faker.gen.ts';
import { UserRole, type UserResponse } from '#lib/api/index.ts';

const mocks = vi.hoisted(() => ({
    authStore: {
        isAuthenticated: true as boolean | null,
        user: null as UserResponse | null,
        waitForInit: vi.fn(),
    },
}));

vi.mock('#stores/auth.svelte.ts', () => ({ authStore: mocks.authStore }));

const url = new URL('https://localhost/editor?lang=go');

async function redirectFrom(guard: Promise<void>): Promise<{ status: number; location: string }> {
    const thrown: unknown = await guard.catch((e: unknown) => e);
    if (!isRedirect(thrown)) throw new Error('expected a redirect');
    return thrown;
}

describe('auth guards', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        sessionStorage.clear();
        mocks.authStore.isAuthenticated = true;
        mocks.authStore.user = { ...fakeUserResponse(), role: UserRole.ADMIN };
        mocks.authStore.waitForInit.mockResolvedValue(true);
    });

    it('lets a signed-in user through', async () => {
        await expect(requireAuth(url)).resolves.toBeUndefined();
    });

    it('sends a signed-out visitor to /login and remembers the path', async () => {
        mocks.authStore.isAuthenticated = false;
        mocks.authStore.waitForInit.mockResolvedValue(false);

        const redirect = await redirectFrom(requireAuth(url));

        expect(redirect.location).toBe('/login');
        expect(sessionStorage.getItem('redirectAfterLogin')).toBe('/editor?lang=go');
    });

    it('treats a failed auth check as signed out', async () => {
        mocks.authStore.waitForInit.mockRejectedValue(new Error('down'));

        expect((await redirectFrom(requireAuth(url))).location).toBe('/login');
    });

    it('lets an admin into admin pages', async () => {
        await expect(requireAdmin(url)).resolves.toBeUndefined();
        expect(toast.error).not.toHaveBeenCalled();
    });

    it('sends a non-admin home with a toast', async () => {
        mocks.authStore.user = { ...fakeUserResponse(), role: UserRole.USER };

        expect((await redirectFrom(requireAdmin(url))).location).toBe('/');
        expect(toast.error).toHaveBeenCalledWith('Admin access required');
    });
});
