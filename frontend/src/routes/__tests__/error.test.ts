import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import ErrorPage from '#routes/+error.svelte';

const mocks = vi.hoisted(() => ({
    page: { status: 404, error: { message: 'Not Found' } as { message: string } | null },
}));

vi.mock('$app/state', () => ({ page: mocks.page }));

describe('+error', () => {
    it.each([
        [404, 'Page not found'],
        [500, 'Something went wrong'],
    ])('shows a %i as "%s"', (status, heading) => {
        mocks.page.status = status;
        render(ErrorPage);
        expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument();
        expect(document.title).toBe(`${status === 404 ? 'Page not found' : 'Error'} - Integr8sCode`);
    });
});
