import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { userPrefersMode } from 'mode-watcher';
import { getUserSettingsApiV1UserSettingsGet, Theme } from '#lib/api/index.ts';
import { fakeUserResponse, fakeUserSettings } from '#lib/api/@faker-js/faker.gen.ts';
import { mockApi } from '#test/test-utils.ts';
import Layout from '#routes/+layout.svelte';

vi.unmock('svelte-sonner');

const children = createRawSnippet(() => ({ render: () => '<p>page body</p>' }));

describe('root layout', () => {
    it('shows the page between the header and the footer, and leaves the saved settings alone when signed out', async () => {
        render(Layout, { props: { data: { user: null }, params: {}, children } });

        await waitFor(() => expect(screen.getByText('page body')).toBeInTheDocument());
        expect(screen.getByRole('banner')).toBeInTheDocument();
        expect(screen.getByRole('contentinfo')).toBeInTheDocument();
        expect(vi.mocked(getUserSettingsApiV1UserSettingsGet)).not.toHaveBeenCalled();
    });

    it('applies the theme saved in the user settings once signed in', async () => {
        userPrefersMode.current = Theme.LIGHT;
        mockApi(getUserSettingsApiV1UserSettingsGet).ok({ ...fakeUserSettings(), theme: Theme.DARK });
        render(Layout, { props: { data: { user: fakeUserResponse() }, params: {}, children } });

        await waitFor(() => expect(userPrefersMode.current).toBe(Theme.DARK));
        await waitFor(() => expect(screen.getByText('page body')).toBeInTheDocument());
    });
});
