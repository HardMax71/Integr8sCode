import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/svelte';
import { proxy } from 'svelte/internal/client';
import { user, createMockUser, mockApi, renderWithQueryClient } from '#test/test-utils.ts';
import RateLimitsModal from '#components/admin/users/RateLimitsModal.svelte';
import {
    getDefaultRateLimitRulesApiV1AdminRateLimitsDefaultsGet,
    zRateLimitRuleRequest,
    type RateLimitRuleResponse,
    type UserRateLimitConfigResponse,
    type UserRateLimitsResponse,
} from '#lib/api/index.ts';

vi.mock('#components/Spinner.svelte', async () => {
    const utils = await import('#test/test-utils.ts');
    return { default: utils.createMockNamedComponents({ default: '<span data-testid="spinner">...</span>' }).default };
});

const createConfig = (rules: RateLimitRuleResponse[] = []): UserRateLimitConfigResponse => ({
    user_id: 'user-1',
    bypass_rate_limit: false,
    global_multiplier: 1,
    notes: '',
    rules,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
});

const usage = (endpoint: string, remaining: number): UserRateLimitsResponse['current_usage'] => ({
    [endpoint]: { algorithm: 'sliding_window', remaining },
});

function renderModal(overrides: Record<string, unknown> = {}) {
    const onClose = vi.fn();
    const onSave = vi.fn();
    const onReset = vi.fn();
    const result = renderWithQueryClient(RateLimitsModal, {
        open: true,
        user: createMockUser({ username: 'alice' }),
        config: proxy(createConfig()),
        usage: null,
        loading: false,
        saving: false,
        onClose,
        onSave,
        onReset,
        ...overrides,
    });
    return { ...result, onClose, onSave, onReset };
}

describe('RateLimitsModal', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockApi(getDefaultRateLimitRulesApiV1AdminRateLimitsDefaultsGet).ok([
            zRateLimitRuleRequest.parse({
                endpoint_pattern: '/api/v1/*',
                group: 'api',
                requests: 100,
                window_seconds: 60,
            }),
        ]);
    });

    it('does not render content when open is false', () => {
        renderModal({ open: false });
        expect(screen.queryByText('Quick Settings')).not.toBeInTheDocument();
    });

    it('shows spinner when loading', () => {
        renderModal({ loading: true, config: null });
        expect(screen.queryByText('Quick Settings')).not.toBeInTheDocument();
    });

    it('displays modal title with username', () => {
        renderModal();
        expect(screen.getByText('Rate Limits for alice')).toBeInTheDocument();
    });

    it.each([
        ['Quick Settings', 'text'],
        ['Bypass Rate Limit', 'label'],
        ['Global Multiplier', 'label'],
        ['Notes', 'label'],
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

    it('labels each default rule field by its key', async () => {
        renderModal();
        const shown = {
            'Endpoint Pattern': '/api/v1/*',
            Requests: '100',
            'Window Seconds': '60',
            Group: 'api',
            Algorithm: 'sliding_window',
        };
        await waitFor(() => expect(screen.getByText('Endpoint Pattern')).toBeInTheDocument());
        for (const [label, value] of Object.entries(shown)) {
            expect(screen.getByText(label).nextElementSibling?.textContent?.trim()).toBe(value);
        }
    });

    it('labels a user rule by its keys and shows the algorithm value', () => {
        renderModal({
            config: proxy(
                createConfig([
                    zRateLimitRuleRequest.parse({
                        endpoint_pattern: '/api/v1/execute',
                        group: 'execution',
                        requests: 5,
                        window_seconds: 30,
                        algorithm: 'token_bucket',
                    }),
                ]),
            ),
        });
        expect(screen.getByText('Rules')).toBeInTheDocument();
        expect(screen.getByLabelText('Endpoint Pattern')).toHaveValue('/api/v1/execute');
        expect(screen.getByLabelText('Requests')).toHaveValue(5);
        expect(screen.getByLabelText('Window Seconds')).toHaveValue(30);
        expect(screen.getByRole('combobox', { name: 'Group' })).toHaveDisplayValue('execution');
        expect(screen.getByRole('combobox', { name: 'Algorithm' })).toHaveDisplayValue('token_bucket');
        expect(screen.getByRole('checkbox', { name: 'Enabled' })).toBeChecked();
    });

    it('shows current usage section when usage data provided', () => {
        renderModal({
            usage: usage('/api/v1/execute', 50),
        });
        expect(screen.getByText('Current Usage')).toBeInTheDocument();
        expect(screen.getByText('/api/v1/execute')).toBeInTheDocument();
        expect(screen.getByText('Remaining').nextElementSibling?.textContent?.trim()).toBe('50');
    });

    it('hides current usage when no usage data', () => {
        renderModal({ usage: null });
        expect(screen.queryByText('Current Usage')).not.toBeInTheDocument();
    });

    it('shows Reset All Counters when usage exists', () => {
        renderModal({
            usage: usage('/api/v1/test', 10),
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

    it('adds a rule from the spec defaults and lets the admin pick its group', async () => {
        renderModal();
        await user.click(screen.getByText('Add Rule'));
        const group = screen.getByRole('combobox', { name: 'Group' });
        expect(group).toHaveDisplayValue('api');
        expect(screen.getByRole('combobox', { name: 'Algorithm' })).toHaveDisplayValue(
            zRateLimitRuleRequest.parse({ endpoint_pattern: '', group: 'api', requests: 1, window_seconds: 1 })
                .algorithm,
        );
        await user.selectOptions(group, 'execution');
        expect(group).toHaveDisplayValue('execution');
    });

    it('shows the effective requests once the multiplier changes', async () => {
        renderModal({ config: proxy({ ...createConfig(), global_multiplier: 2 }) });
        await waitFor(() => expect(screen.getByText('200')).toBeInTheDocument());
    });
});
