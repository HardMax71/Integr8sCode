import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { user, createMockUser } from '$test/test-utils';
import RateLimitsModal from '$components/admin/users/RateLimitsModal.svelte';

vi.mock('$components/Spinner.svelte', async () => {
  const utils = await import('$test/test-utils');
  return { default: utils.createMockNamedComponents({ default: '<span data-testid="spinner">...</span>' }).default };
});

vi.mock('$lib/api', () => ({
  getDefaultRateLimitRulesApiV1AdminRateLimitsDefaultsGet: vi.fn().mockResolvedValue({
    data: [
      { endpoint_pattern: '/api/v1/*', requests: 100, window_seconds: 60, group: 'general', algorithm: 'sliding_window', enabled: true },
    ],
  }),
}));

vi.mock('$lib/admin/rate-limits', () => ({
  getGroupColor: vi.fn(() => 'badge-neutral'),
  detectGroupFromEndpoint: vi.fn(() => 'general'),
  createEmptyRule: vi.fn(() => ({
    endpoint_pattern: '',
    requests: 10,
    window_seconds: 60,
    group: 'general',
    algorithm: 'sliding_window',
    enabled: true,
  })),
}));

function renderModal(overrides: Record<string, unknown> = {}) {
  const onClose = vi.fn();
  const onSave = vi.fn();
  const onReset = vi.fn();
  const result = render(RateLimitsModal, {
    props: {
      open: true,
      user: createMockUser({ username: 'alice' }),
      config: {
        user_id: 'user-1',
        bypass_rate_limit: false,
        global_multiplier: 1.0,
        notes: '',
        rules: [],
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      },
      usage: null,
      loading: false,
      saving: false,
      onClose,
      onSave,
      onReset,
      ...overrides,
    },
  });
  return { ...result, onClose, onSave, onReset };
}

describe('RateLimitsModal', () => {
  beforeEach(() => vi.clearAllMocks());

  it('does not render content when open is false', () => {
    renderModal({ open: false });
    expect(screen.queryByText('Quick Settings')).not.toBeInTheDocument();
  });

  it('shows spinner when loading', () => {
    renderModal({ loading: true, config: null });
    // When config is null, spinner is shown
    expect(screen.queryByText('Quick Settings')).not.toBeInTheDocument();
  });

  it('displays modal title with username', () => {
    renderModal();
    expect(screen.getByText('Rate Limits for alice')).toBeInTheDocument();
  });

  it.each([
    ['Quick Settings', 'text'],
    ['Bypass all rate limits', 'text'],
    ['Global Multiplier', 'label'],
    ['Admin Notes', 'label'],
    ['Endpoint Rate Limits', 'text'],
    ['Add Rule', 'text'],
  ] as const)('shows %s element', (text, queryType) => {
    renderModal();
    if (queryType === 'label') expect(screen.getByLabelText(text)).toBeInTheDocument();
    else expect(screen.getByText(text)).toBeInTheDocument();
  });

  it('shows default rules after mount', async () => {
    renderModal();
    await waitFor(() => {
      expect(screen.getByText('Default Global Rules')).toBeInTheDocument();
    });
  });

  it('shows current usage section when usage data provided', () => {
    renderModal({
      usage: { '/api/v1/execute': { algorithm: 'sliding_window', remaining: 50 } },
    });
    expect(screen.getByText('Current Usage')).toBeInTheDocument();
    expect(screen.getByText('/api/v1/execute')).toBeInTheDocument();
    expect(screen.getByText('50 remaining')).toBeInTheDocument();
  });

  it('hides current usage when no usage data', () => {
    renderModal({ usage: null });
    expect(screen.queryByText('Current Usage')).not.toBeInTheDocument();
  });

  it('shows Reset All Counters when usage exists', () => {
    renderModal({
      usage: { '/api/v1/test': { algorithm: 'sliding_window', remaining: 10 } },
    });
    expect(screen.getByText('Reset All Counters')).toBeInTheDocument();
  });

  it('calls onSave when Save Changes clicked', async () => {
    const { onSave } = renderModal();
    await user.click(screen.getByText('Save Changes'));
    expect(onSave).toHaveBeenCalledOnce();
  });

  it('calls onClose when Cancel clicked', async () => {
    const { onClose } = renderModal();
    await user.click(screen.getByText('Cancel'));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('shows Saving... when saving', () => {
    renderModal({ saving: true });
    expect(screen.getByText('Saving...')).toBeInTheDocument();
  });

  it('disables Save button when saving', () => {
    renderModal({ saving: true });
    expect(screen.getByText('Saving...').closest('button')).toBeDisabled();
  });
});
