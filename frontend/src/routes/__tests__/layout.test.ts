import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { userPrefersMode } from 'mode-watcher';
import { getUserSettingsApiV1UserSettingsGet, Theme, zUserSettings } from '#lib/api/index.ts';
import { mockApi } from '#test/test-utils.ts';
import Layout from '#routes/+layout.svelte';

const mocks = vi.hoisted(() => ({ initialize: vi.fn(), authStore: { isAuthenticated: false as boolean } }));

vi.mock('#stores/auth.svelte.ts', () => ({
    authStore: {
        initialize: mocks.initialize,
        get isAuthenticated() {
            return mocks.authStore.isAuthenticated;
        },
    },
}));
vi.mock('#components/Header.svelte', async () => {
    const utils = await import('#test/test-utils.ts');
    return { default: utils.createMockNamedComponents({ default: '<header>header</header>' }).default };
});
vi.mock('#components/Footer.svelte', async () => {
    const utils = await import('#test/test-utils.ts');
    return { default: utils.createMockNamedComponents({ default: '<footer>footer</footer>' }).default };
});
vi.mock('svelte-sonner', async () => {
    const utils = await import('#test/test-utils.ts');
    return {
        toast: { success: vi.fn(), error: vi.fn() },
        Toaster: utils.createMockNamedComponents({ default: '' }).default,
    };
});

const children = createRawSnippet(() => ({ render: () => '<p>page body</p>' }));

describe('root layout', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.authStore.isAuthenticated = false;
    });

    it('shows the page once the auth check finishes', async () => {
        mocks.initialize.mockResolvedValue(true);
        render(Layout, { props: { children } });

        await waitFor(() => expect(screen.getByText('page body')).toBeInTheDocument());
        expect(mocks.initialize).toHaveBeenCalledOnce();
    });

    it('still shows the page when the auth check fails', async () => {
        mocks.initialize.mockRejectedValue(new Error('down'));
        render(Layout, { props: { children } });

        await waitFor(() => expect(screen.getByText('page body')).toBeInTheDocument());
    });

    it('applies the theme saved in the user settings once signed in', async () => {
        mocks.initialize.mockResolvedValue(true);
        mocks.authStore.isAuthenticated = true;
        userPrefersMode.current = Theme.LIGHT;
        mockApi(getUserSettingsApiV1UserSettingsGet).ok(
            zUserSettings.parse({
                user_id: 'user-1',
                theme: Theme.DARK,
                notifications: {},
                editor: {},
                custom_settings: {},
                created_at: '2024-01-15T10:30:00Z',
                updated_at: '2024-01-15T10:30:00Z',
            }),
        );
        render(Layout, { props: { children } });

        await waitFor(() => expect(userPrefersMode.current).toBe(Theme.DARK));
        await waitFor(() => expect(screen.getByText('page body')).toBeInTheDocument());
    });
});
