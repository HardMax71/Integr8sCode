import { describe, it, expect, beforeEach, vi } from 'vitest';
import { isRedirect } from '@sveltejs/kit';
import { requireAdmin, requireAuth } from '#lib/auth-guard.ts';
import { ssr } from '#routes/+layout.ts';
import { load as authGroupLoad } from '#routes/(auth)/+layout.ts';
import { load as adminLoad } from '#routes/admin/+layout.ts';
import { load as adminIndexLoad } from '#routes/admin/+page.ts';

vi.mock('#lib/auth-guard.ts', () => ({ requireAuth: vi.fn(), requireAdmin: vi.fn() }));

const url = new URL('https://localhost/editor');

describe('route files', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('renders every page in the browser only', () => {
        expect(ssr).toBe(false);
    });

    it('guards the (auth) group with requireAuth', async () => {
        await authGroupLoad({ url } as Parameters<typeof authGroupLoad>[0]);
        expect(vi.mocked(requireAuth)).toHaveBeenCalledWith(url);
    });

    it('guards the admin pages with requireAdmin', async () => {
        await adminLoad({ url } as Parameters<typeof adminLoad>[0]);
        expect(vi.mocked(requireAdmin)).toHaveBeenCalledWith(url);
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
