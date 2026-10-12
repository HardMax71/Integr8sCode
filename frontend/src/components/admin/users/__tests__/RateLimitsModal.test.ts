import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/svelte';
import { user, mockApi, renderWithQueryClient } from '#test/test-utils.ts';
import {
    fakeRateLimitUpdateResponse,
    fakeUserRateLimitConfigResponse,
    fakeUserRateLimitsResponse,
    fakeUserResponse,
} from '#lib/api/@faker-js/faker.gen.ts';
import RateLimitsModal from '#components/admin/users/RateLimitsModal.svelte';
import {
    getDefaultRateLimitRulesApiV1AdminRateLimitsDefaultsGet,
    getUserRateLimitsApiV1AdminRateLimitsUserIdGet,
    resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPost,
    updateUserRateLimitsApiV1AdminRateLimitsUserIdPut,
    zRateLimitRuleRequest,
    zRateLimitUpdateRequest,
    type UserRateLimitConfigResponse,
    type UserRateLimitsResponse,
} from '#lib/api/index.ts';

const createConfig = (overrides: Partial<UserRateLimitConfigResponse> = {}): UserRateLimitConfigResponse => ({
    ...fakeUserRateLimitConfigResponse(),
    bypass_rate_limit: false,
    global_multiplier: 1,
    notes: '',
    rules: [],
    ...overrides,
});

const updateLimits = () => vi.mocked(updateUserRateLimitsApiV1AdminRateLimitsUserIdPut);

function renderModal(limits: Partial<UserRateLimitsResponse> = {}) {
    mockApi(getUserRateLimitsApiV1AdminRateLimitsUserIdGet).ok({
        ...fakeUserRateLimitsResponse(),
        rate_limit_config: createConfig(),
        current_usage: {},
        ...limits,
    });
    const onClose = vi.fn();
    renderWithQueryClient(RateLimitsModal, {
        user: { ...fakeUserResponse(), user_id: 'user-1', username: 'alice' },
        onClose,
    });
    return { onClose };
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
        mockApi(updateUserRateLimitsApiV1AdminRateLimitsUserIdPut).ok(fakeRateLimitUpdateResponse());
        mockApi(resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPost).ok({ message: 'reset' });
    });

    it('shows a spinner while the limits load', () => {
        mockApi(getUserRateLimitsApiV1AdminRateLimitsUserIdGet).mock.mockImplementation(() => new Promise(() => {}));
        renderWithQueryClient(RateLimitsModal, { user: fakeUserResponse(), onClose: vi.fn() });
        expect(screen.getByRole('status', { name: 'Loading' })).toBeInTheDocument();
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
    ] as const)('shows %s element', async (text, queryType) => {
        renderModal();
        await screen.findByText('Quick Settings');
        if (queryType === 'label') expect(screen.getByLabelText(text)).toBeInTheDocument();
        else expect(screen.getByText(text)).toBeInTheDocument();
    });

    it('starts from the API defaults when the user has no config', async () => {
        renderModal({ rate_limit_config: null });
        expect(await screen.findByLabelText('Global Multiplier')).toHaveValue(
            zRateLimitUpdateRequest.parse({}).global_multiplier,
        );
        expect(screen.getByLabelText('Bypass Rate Limit')).not.toBeChecked();
    });

    it('shows default rules after mount', async () => {
        renderModal();
        expect(await screen.findByText('Default Global Rules')).toBeInTheDocument();
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
        await waitFor(() => expect(screen.getByText('/api/v1/*')).toBeInTheDocument());
        for (const [label, value] of Object.entries(shown)) {
            expect(screen.getByText(label).nextElementSibling?.textContent?.trim()).toBe(value);
        }
    });

    it('labels a user rule by its keys and shows the algorithm value', async () => {
        renderModal({
            rate_limit_config: createConfig({
                rules: [
                    zRateLimitRuleRequest.parse({
                        endpoint_pattern: '/api/v1/execute',
                        group: 'execution',
                        requests: 5,
                        window_seconds: 30,
                        algorithm: 'token_bucket',
                    }),
                ],
            }),
        });
        expect(await screen.findByText('Rules')).toBeInTheDocument();
        expect(screen.getByLabelText('Endpoint Pattern')).toHaveValue('/api/v1/execute');
        expect(screen.getByLabelText('Requests')).toHaveValue(5);
        expect(screen.getByLabelText('Window Seconds')).toHaveValue(30);
        expect(screen.getByRole('combobox', { name: 'Group' })).toHaveDisplayValue('execution');
        expect(screen.getByRole('combobox', { name: 'Algorithm' })).toHaveDisplayValue('token_bucket');
        expect(screen.getByRole('checkbox', { name: 'Enabled' })).toBeChecked();
    });

    it('shows current usage section when usage data provided', async () => {
        renderModal({ current_usage: { '/api/v1/execute': { algorithm: 'sliding_window', remaining: 50 } } });
        expect(await screen.findByText('Current Usage')).toBeInTheDocument();
        expect(screen.getByText('/api/v1/execute')).toBeInTheDocument();
        expect(screen.getByText('Remaining').nextElementSibling?.textContent?.trim()).toBe('50');
    });

    it('hides current usage when no usage data', async () => {
        renderModal();
        await screen.findByText('Quick Settings');
        expect(screen.queryByText('Current Usage')).not.toBeInTheDocument();
    });

    it('resets the counters for this user', async () => {
        renderModal({ current_usage: { '/api/v1/test': { algorithm: 'sliding_window', remaining: 10 } } });
        await user.click(await screen.findByText('Reset All Counters'));
        await waitFor(() =>
            expect(vi.mocked(resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPost)).toHaveBeenCalledWith(
                expect.objectContaining({ path: { user_id: 'user-1' } }),
            ),
        );
    });

    it('saves the edited config and closes', async () => {
        const { onClose } = renderModal();
        await user.click(await screen.findByLabelText('Bypass Rate Limit'));
        await user.click(screen.getByText('Save Changes'));

        await waitFor(() =>
            expect(updateLimits()).toHaveBeenCalledWith(
                expect.objectContaining({
                    path: { user_id: 'user-1' },
                    body: expect.objectContaining({ bypass_rate_limit: true, global_multiplier: 1, rules: [] }),
                }),
            ),
        );
        await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    });

    it('calls onClose when Cancel clicked', async () => {
        const { onClose } = renderModal();
        await user.click(await screen.findByText('Cancel'));
        expect(onClose).toHaveBeenCalledOnce();
        expect(updateLimits()).not.toHaveBeenCalled();
    });

    it('shows Saving... and disables Save while saving', async () => {
        mockApi(updateUserRateLimitsApiV1AdminRateLimitsUserIdPut).mock.mockImplementation(() => new Promise(() => {}));
        renderModal();
        await user.click(await screen.findByText('Save Changes'));
        expect((await screen.findByText('Saving...')).closest('button')).toBeDisabled();
    });

    it('adds a rule from the spec defaults and lets the admin pick its group', async () => {
        renderModal();
        await user.click(await screen.findByText('Add Rule'));
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
        renderModal({ rate_limit_config: createConfig({ global_multiplier: 2 }) });
        expect(await screen.findByText('200')).toBeInTheDocument();
    });
});
