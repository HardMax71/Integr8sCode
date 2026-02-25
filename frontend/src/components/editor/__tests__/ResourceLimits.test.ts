import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { user } from '$test/test-utils';


import ResourceLimits from '../ResourceLimits.svelte';

const LIMITS = {
  cpu_limit: '500m',
  memory_limit: '256Mi',
  cpu_request: '100m',
  memory_request: '64Mi',
  execution_timeout: 30,
  supported_runtimes: {},
};

describe('ResourceLimits', () => {
  it('renders nothing when limits is null', () => {
    const { container } = render(ResourceLimits, { props: { limits: null } });
    expect(container.textContent?.trim()).toBe('');
  });

  it('renders collapsed toggle button with aria-expanded=false when limits provided', () => {
    render(ResourceLimits, { props: { limits: LIMITS } });
    const btn = screen.getByRole('button', { name: /Resource Limits/i });
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveAttribute('aria-expanded', 'false');
  });

  it('expands panel on click showing all limit values', async () => {
    render(ResourceLimits, { props: { limits: LIMITS } });
    await user.click(screen.getByRole('button', { name: /Resource Limits/i }));

    expect(screen.getByRole('button', { name: /Resource Limits/i })).toHaveAttribute('aria-expanded', 'true');
  });

  it.each([
    { label: 'CPU Limit', value: '500m' },
    { label: 'Memory Limit', value: '256Mi' },
    { label: 'Timeout', value: '30s' },
  ])('shows $label = $value when expanded', async ({ label, value }) => {
    render(ResourceLimits, { props: { limits: LIMITS } });
    await user.click(screen.getByRole('button', { name: /Resource Limits/i }));
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText(value)).toBeInTheDocument();
  });

  it('collapses panel on second click', async () => {
    render(ResourceLimits, { props: { limits: LIMITS } });
    const btn = screen.getByRole('button', { name: /Resource Limits/i });

    await user.click(btn);
    expect(btn).toHaveAttribute('aria-expanded', 'true');

    await user.click(btn);
    expect(btn).toHaveAttribute('aria-expanded', 'false');
  });
});
