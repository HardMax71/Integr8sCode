import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import Layout from '#routes/+layout.svelte';

const mocks = vi.hoisted(() => ({ initialize: vi.fn() }));

vi.mock('#stores/auth.svelte.ts', () => ({ authStore: { initialize: mocks.initialize } }));
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
});
