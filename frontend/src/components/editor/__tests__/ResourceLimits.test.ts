import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/svelte';
import { mockApi, renderWithQueryClient, user } from '#test/test-utils.ts';
import { fakeResourceLimits } from '#lib/api/@faker-js/faker.gen.ts';

import ResourceLimits from '#components/editor/ResourceLimits.svelte';
import { getK8sResourceLimitsApiV1K8sLimitsGet } from '#lib/api/index.ts';
import { draft } from '#lib/editor/draft.svelte.ts';

function renderLimits(lang: string) {
    mockApi(getK8sResourceLimitsApiV1K8sLimitsGet).ok({
        ...fakeResourceLimits(),
        supported_runtimes: {
            python: { versions: ['3.14'], file_ext: 'py' },
            go: { versions: ['1.27'], file_ext: 'go' },
            ruby: { versions: ['3.4'], file_ext: 'rb' },
        },
        language_limits: {
            python: { cpu_limit: '500m', memory_limit: '256Mi', execution_timeout: 30 },
            go: { cpu_limit: '1000m', memory_limit: '320Mi', execution_timeout: 45 },
        },
    });
    draft.current = { ...draft.current, lang };
    return renderWithQueryClient(ResourceLimits);
}

const trigger = () => screen.findByRole('button', { name: /Resource Limits/i });

describe('ResourceLimits', () => {
    it('opens a panel from a collapsed trigger', async () => {
        renderLimits('python');
        const button = await trigger();
        expect(button).toHaveAttribute('aria-expanded', 'false');
        await user.click(button);
        expect(button).toHaveAttribute('aria-expanded', 'true');
    });

    it.each([
        { lang: 'python', label: 'Cpu Limit', value: '500m' },
        { lang: 'python', label: 'Memory Limit', value: '256Mi' },
        { lang: 'python', label: 'Execution Timeout', value: '30s' },
        { lang: 'go', label: 'Cpu Limit', value: '1000m' },
        { lang: 'go', label: 'Memory Limit', value: '320Mi' },
        { lang: 'go', label: 'Execution Timeout', value: '45s' },
    ])('shows the effective $label = $value for $lang', async ({ lang, label, value }) => {
        renderLimits(lang);
        await user.click(await trigger());
        expect(screen.getByText(label)).toBeInTheDocument();
        expect(screen.getByText(value)).toBeInTheDocument();
    });

    it('renders nothing for a language the API lists no limits for', async () => {
        const { container } = renderLimits('ruby');
        await waitFor(() => expect(vi.mocked(getK8sResourceLimitsApiV1K8sLimitsGet)).toHaveBeenCalled());
        expect(container.textContent?.trim()).toBe('');
    });
});
