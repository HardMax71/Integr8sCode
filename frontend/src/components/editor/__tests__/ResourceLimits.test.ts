import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { createMockResourceLimits, user } from '#test/test-utils.ts';

import ResourceLimits from '#components/editor/ResourceLimits.svelte';

const LIMITS = createMockResourceLimits({
    language_limits: {
        python: { cpu_limit: '500m', memory_limit: '256Mi', execution_timeout: 30 },
        go: { cpu_limit: '1000m', memory_limit: '320Mi', execution_timeout: 45 },
    },
});

describe('ResourceLimits', () => {
    it('renders nothing when limits is null', () => {
        const { container } = render(ResourceLimits, { props: { limits: null, lang: 'python' } });
        expect(container.textContent?.trim()).toBe('');
    });

    it('renders collapsed toggle button with aria-expanded=false when limits provided', () => {
        render(ResourceLimits, { props: { limits: LIMITS, lang: 'python' } });
        const btn = screen.getByRole('button', { name: /Resource Limits/i });
        expect(btn).toBeInTheDocument();
        expect(btn).toHaveAttribute('aria-expanded', 'false');
    });

    it('expands panel on click showing all limit values', async () => {
        render(ResourceLimits, { props: { limits: LIMITS, lang: 'python' } });
        await user.click(screen.getByRole('button', { name: /Resource Limits/i }));

        expect(screen.getByRole('button', { name: /Resource Limits/i })).toHaveAttribute('aria-expanded', 'true');
    });

    it.each([
        { lang: 'python', label: 'Cpu Limit', value: '500m' },
        { lang: 'python', label: 'Memory Limit', value: '256Mi' },
        { lang: 'python', label: 'Execution Timeout', value: '30s' },
        { lang: 'go', label: 'Cpu Limit', value: '1000m' },
        { lang: 'go', label: 'Memory Limit', value: '320Mi' },
        { lang: 'go', label: 'Execution Timeout', value: '45s' },
    ])('shows the effective $label = $value for $lang', async ({ lang, label, value }) => {
        render(ResourceLimits, { props: { limits: LIMITS, lang } });
        await user.click(screen.getByRole('button', { name: /Resource Limits/i }));
        expect(screen.getByText(label)).toBeInTheDocument();
        expect(screen.getByText(value)).toBeInTheDocument();
    });

    it('renders nothing for a language the API lists no limits for', () => {
        const { container } = render(ResourceLimits, { props: { limits: LIMITS, lang: 'ruby' } });
        expect(container.textContent?.trim()).toBe('');
    });

    it('collapses panel on second click', async () => {
        render(ResourceLimits, { props: { limits: LIMITS, lang: 'python' } });
        const btn = screen.getByRole('button', { name: /Resource Limits/i });

        await user.click(btn);
        expect(btn).toHaveAttribute('aria-expanded', 'true');

        await user.click(btn);
        expect(btn).toHaveAttribute('aria-expanded', 'false');
    });
});
