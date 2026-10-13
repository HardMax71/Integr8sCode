import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/svelte';
import { user, mockApi, renderWithQueryClient } from '#test/test-utils.ts';
import { fakeSagaStatusResponse } from '#lib/api/@faker-js/faker.gen.ts';
import { getSagaStatusApiV1SagasSagaIdGet, type SagaStatusResponse } from '#lib/api/index.ts';
import { fieldTitle } from '#lib/formatters.ts';
import SagaDetailsModal from '#components/admin/sagas/SagaDetailsModal.svelte';

vi.mock('#lib/formatters.ts', async (importOriginal) => ({
    ...(await importOriginal<typeof import('#lib/formatters.ts')>()),
    formatTimestamp: vi.fn((ts: string | null) => (ts ? `ts:${ts}` : 'N/A')),
    formatDurationBetween: vi.fn(() => '1m 30s'),
}));

vi.mock('#lib/admin/sagas/index.ts', () => ({
    getSagaStateInfo: vi.fn(() => ({ color: 'badge-neutral' })),
}));

async function renderModal(saga: SagaStatusResponse = fakeSagaStatusResponse()) {
    mockApi(getSagaStatusApiV1SagasSagaIdGet).ok(saga);
    const onClose = vi.fn();
    const onViewExecution = vi.fn();
    const result = renderWithQueryClient(SagaDetailsModal, { sagaId: saga.saga_id, onClose, onViewExecution });
    await screen.findByText('Basic Information');
    return { ...result, onClose, onViewExecution };
}

describe('SagaDetailsModal', () => {
    it('loads the saga by its id', async () => {
        await renderModal({ ...fakeSagaStatusResponse(), saga_id: 'saga-7' });
        await waitFor(() =>
            expect(vi.mocked(getSagaStatusApiV1SagasSagaIdGet)).toHaveBeenCalledWith(
                expect.objectContaining({ path: { saga_id: 'saga-7' } }),
            ),
        );
    });

    it('shows only the title until the saga has loaded', async () => {
        vi.mocked(getSagaStatusApiV1SagasSagaIdGet).mockReturnValue(new Promise<never>(() => {}));
        renderWithQueryClient(SagaDetailsModal, { sagaId: 'saga-1', onClose: vi.fn(), onViewExecution: vi.fn() });
        expect(screen.getByText('Saga Details')).toBeInTheDocument();
        expect(screen.queryByText('Basic Information')).not.toBeInTheDocument();
    });

    it.each(['Saga Details', 'Basic Information', 'Timing Information', 'Execution Steps'])(
        'shows %s section',
        async (section) => {
            await renderModal();
            expect(screen.getByText(section)).toBeInTheDocument();
        },
    );

    it.each([
        'saga_id',
        'saga_name',
        'execution_id',
        'state',
        'retry_count',
        'created_at',
        'updated_at',
        'completed_at',
    ])('labels the %s field by its API name', async (key) => {
        await renderModal();
        expect(screen.getByText(fieldTitle(key), { selector: 'dt' })).toBeInTheDocument();
    });

    it('displays saga ID', async () => {
        await renderModal({ ...fakeSagaStatusResponse(), saga_id: 'saga-test-123' });
        expect(screen.getByText('saga-test-123')).toBeInTheDocument();
    });

    it('displays saga name', async () => {
        await renderModal({ ...fakeSagaStatusResponse(), saga_name: 'test_saga' });
        expect(screen.getByText('test_saga')).toBeInTheDocument();
    });

    it('displays execution ID as clickable button', async () => {
        const saga = { ...fakeSagaStatusResponse(), execution_id: 'exec-999' };
        await renderModal(saga);
        expect(screen.getByText('exec-999')).toBeInTheDocument();
    });

    it('displays state badge', async () => {
        await renderModal({ ...fakeSagaStatusResponse(), state: 'completed' });
        expect(screen.getByText('completed')).toHaveClass('badge');
    });

    it('displays retry count', async () => {
        await renderModal({ ...fakeSagaStatusResponse(), retry_count: 5 });
        expect(screen.getByText('5')).toBeInTheDocument();
    });

    it('shows completed steps count', async () => {
        await renderModal({ ...fakeSagaStatusResponse(), completed_steps: ['step1', 'step2'] });
        expect(screen.getByText('Completed Steps (2)')).toBeInTheDocument();
    });

    it('lists completed steps', async () => {
        await renderModal({ ...fakeSagaStatusResponse(), completed_steps: ['validate', 'allocate'] });
        expect(screen.getByText('validate')).toBeInTheDocument();
        expect(screen.getByText('allocate')).toBeInTheDocument();
    });

    it.each([
        ['completed', 'No completed steps'],
        ['compensated', 'No compensated steps'],
    ] as const)('shows "%s" empty state when no steps', async (_type, emptyText) => {
        await renderModal({ ...fakeSagaStatusResponse(), completed_steps: [], compensated_steps: [] });
        expect(screen.getByText(emptyText)).toBeInTheDocument();
    });

    it('shows compensated steps count', async () => {
        await renderModal({ ...fakeSagaStatusResponse(), compensated_steps: ['step1'] });
        expect(screen.getByText('Compensated Steps (1)')).toBeInTheDocument();
    });

    it.each([
        ['current step', { current_step: 'create_pod' }, 'Current Step', 'create_pod'],
        ['error message', { error_message: 'Pod creation failed' }, 'Error Message', 'Pod creation failed'],
    ] as const)('shows %s when present', async (_label, overrides, sectionText, valueText) => {
        await renderModal({ ...fakeSagaStatusResponse(), ...overrides });
        expect(screen.getByText(sectionText)).toBeInTheDocument();
        expect(screen.getByText(valueText)).toBeInTheDocument();
    });

    it.each([
        ['current step', { current_step: null }, 'Current Step'],
        ['error section', { error_message: null }, 'Error Message'],
    ] as const)('hides %s when null', async (_label, overrides, hiddenText) => {
        await renderModal({ ...fakeSagaStatusResponse(), ...overrides });
        expect(screen.queryByText(hiddenText)).not.toBeInTheDocument();
    });

    it('calls onViewExecution when execution ID button clicked', async () => {
        const saga = { ...fakeSagaStatusResponse(), execution_id: 'exec-click' };
        const { onViewExecution, onClose } = await renderModal(saga);
        await user.click(screen.getByText('exec-click'));
        expect(onClose).toHaveBeenCalledOnce();
        expect(onViewExecution).toHaveBeenCalledWith('exec-click');
    });
});
