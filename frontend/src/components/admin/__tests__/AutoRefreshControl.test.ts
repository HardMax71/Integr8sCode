import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { user } from '$test/test-utils';
import AutoRefreshControl from '$components/admin/AutoRefreshControl.svelte';

vi.mock('$components/Spinner.svelte', async () => {
  const utils = await import('$test/test-utils');
  return { default: utils.createMockNamedComponents({ default: '<span data-testid="spinner">...</span>' }).default };
});

function renderControl(overrides: Record<string, unknown> = {}) {
  const onRefresh = vi.fn();
  const onEnabledChange = vi.fn();
  const onRateChange = vi.fn();
  const result = render(AutoRefreshControl, {
    props: {
      enabled: true,
      rate: 5,
      loading: false,
      onRefresh,
      onEnabledChange,
      onRateChange,
      ...overrides,
    },
  });
  return { ...result, onRefresh, onEnabledChange, onRateChange };
}

describe('AutoRefreshControl', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders auto-refresh checkbox', () => {
    renderControl();
    expect(screen.getByText('Auto-refresh')).toBeInTheDocument();
  });

  it.each([
    [true, true, true],
    [false, false, false],
  ] as const)('when enabled=%s: checkbox checked=%s, rate selector visible=%s', (enabled, checked, rateVisible) => {
    renderControl({ enabled });
    const checkbox = screen.getByRole('checkbox');
    if (checked) expect(checkbox).toBeChecked();
    else expect(checkbox).not.toBeChecked();
    if (rateVisible) expect(screen.getByLabelText(/Every/)).toBeInTheDocument();
    else expect(screen.queryByLabelText(/Every/)).not.toBeInTheDocument();
  });

  it.each([
    [false, 'Refresh Now', false],
    [true, 'Refreshing...', true],
  ] as const)('when loading=%s: shows "%s" button, disabled=%s', (loading, text, disabled) => {
    renderControl({ loading });
    const btn = screen.getByText(text).closest('button')!;
    expect(btn).toBeInTheDocument();
    if (disabled) expect(btn).toBeDisabled();
    else expect(btn).toBeEnabled();
  });

  it('calls onRefresh when Refresh Now clicked', async () => {
    const { onRefresh } = renderControl();
    await user.click(screen.getByText('Refresh Now'));
    expect(onRefresh).toHaveBeenCalledOnce();
  });

  it('rate selector has default options', () => {
    renderControl({ enabled: true });
    const select = screen.getByLabelText(/Every/) as HTMLSelectElement;
    const labels = Array.from(select.options).map(o => o.text);
    expect(labels).toEqual(['5 seconds', '10 seconds', '30 seconds', '1 minute']);
  });
});
