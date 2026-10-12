import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/svelte';
import { user } from '#test/test-utils.ts';
import { fakeExecutionResult } from '#lib/api/@faker-js/faker.gen.ts';
import { toast } from 'svelte-sonner';
import { ExecutionStatus, type ExecutionResult } from '#lib/api/index.ts';
import type { ExecutionPhase } from '#lib/editor/index.ts';

import OutputPanel from '#components/editor/OutputPanel.svelte';

type IdleProps = { phase: ExecutionPhase; result: ExecutionResult | null; error: string | null };

function renderIdle(overrides: Partial<IdleProps> = {}) {
    return render(OutputPanel, {
        props: { phase: 'idle' as ExecutionPhase, result: null, error: null, ...overrides },
    });
}

describe('OutputPanel', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('shows heading and prompt text when idle with no result or error', () => {
        renderIdle();
        expect(screen.getByText('Execution Output')).toBeInTheDocument();
        expect(screen.getByText(/Write some code and click "Run Script"/)).toBeInTheDocument();
    });

    describe('spinner phases', () => {
        it.each([
            ['starting', 'Starting...'],
            ['queued', 'Queued...'],
            ['scheduled', 'Scheduled...'],
            ['running', 'Running...'],
        ] as const)('phase "%s" shows spinner with label "%s"', (phase, label) => {
            renderIdle({ phase: phase as ExecutionPhase });
            expect(screen.getByText(label)).toBeInTheDocument();
            expect(screen.queryByText(/Write some code/)).not.toBeInTheDocument();
        });
    });

    it('shows error message when error present and no result', () => {
        renderIdle({ error: 'Connection timeout' });
        expect(screen.getByText('Execution Failed')).toBeInTheDocument();
        expect(screen.getByText('Connection timeout')).toBeInTheDocument();
    });

    describe('result rendering', () => {
        const BADGE_CLASSES: Record<ExecutionStatus, string> = {
            queued: 'badge-neutral',
            scheduled: 'badge-neutral',
            running: 'badge-info',
            completed: 'badge-success',
            failed: 'badge-danger',
            timeout: 'badge-warning',
            cancelled: 'badge-neutral',
            error: 'badge-danger',
        };

        it.each(Object.values(ExecutionStatus))('status "%s" shows its badge', async (status) => {
            renderIdle({ result: { ...fakeExecutionResult(), status } });
            const badge = await screen.findByText(status);
            expect(badge).toHaveClass('badge', BADGE_CLASSES[status]);
            expect(within(badge).getByText('Status')).toBeInTheDocument();
        });

        it.each([
            { field: 'stdout', heading: 'Stdout', content: 'Hello World!' },
            { field: 'stderr', heading: 'Stderr', content: 'NameError: x is not defined' },
        ])('shows $heading when $field present', async ({ field, heading, content }) => {
            renderIdle({ result: { ...fakeExecutionResult(), [field]: content } });
            await waitFor(() => expect(screen.getByText(heading)).toBeInTheDocument());
        });

        it('hides stdout and stderr sections when both null', async () => {
            renderIdle({ result: { ...fakeExecutionResult(), stdout: null, stderr: null } });
            await waitFor(() => expect(screen.getByText('Status')).toBeInTheDocument());
            expect(screen.queryByText('Stdout')).not.toBeInTheDocument();
            expect(screen.queryByText('Stderr')).not.toBeInTheDocument();
        });

        it('shows execution ID copy button when execution_id present', async () => {
            renderIdle({ result: { ...fakeExecutionResult(), execution_id: 'abc-123' } });
            await waitFor(() => expect(screen.getByLabelText('Click to copy execution ID')).toBeInTheDocument());
        });
    });

    describe('resource usage', () => {
        it.each([
            {
                usage: {
                    cpu_time_jiffies: 50,
                    clk_tck_hertz: 100,
                    peak_memory_kb: 10240,
                    execution_time_wall_seconds: 2.345,
                },
                shown: { 'Execution Time Wall Seconds': '2.345', 'Cpu Time Jiffies': '50', 'Peak Memory Kb': '10240' },
            },
            {
                usage: {
                    cpu_time_jiffies: 0,
                    clk_tck_hertz: 100,
                    peak_memory_kb: 2048,
                    execution_time_wall_seconds: 0.5,
                },
                shown: { 'Execution Time Wall Seconds': '0.500', 'Cpu Time Jiffies': '0', 'Peak Memory Kb': '2048' },
            },
        ])('shows each field in its own unit: $shown', async ({ usage, shown }) => {
            renderIdle({ result: { ...fakeExecutionResult(), resource_usage: usage } });
            await waitFor(() => expect(screen.getByText('Resource Usage')).toBeInTheDocument());
            for (const [label, value] of Object.entries(shown)) {
                expect(screen.getByText(label).nextElementSibling?.textContent?.trim()).toBe(value);
            }
        });

        it('hides resource usage when not present', () => {
            renderIdle({ result: { ...fakeExecutionResult(), resource_usage: null } });
            expect(screen.queryByText('Resource Usage')).not.toBeInTheDocument();
        });
    });

    describe('copy to clipboard', () => {
        let writeTextMock: ReturnType<typeof vi.fn>;

        function mockClipboard(resolves = true) {
            writeTextMock = resolves
                ? vi.fn().mockResolvedValue(undefined)
                : vi.fn().mockRejectedValue(new Error('denied'));
            Object.defineProperty(navigator, 'clipboard', {
                value: { writeText: writeTextMock },
                writable: true,
                configurable: true,
            });
        }

        it.each([
            { target: 'stdout', ariaLabel: 'Copy output to clipboard', text: 'hello world', toastLabel: 'Output' },
            {
                target: 'stderr',
                ariaLabel: 'Copy error text to clipboard',
                text: 'some error',
                toastLabel: 'Error text',
            },
            {
                target: 'execution_id',
                ariaLabel: 'Click to copy execution ID',
                text: 'uuid-abc',
                toastLabel: 'Execution ID',
            },
        ])('copies $target and shows success toast', async ({ target, ariaLabel, text, toastLabel }) => {
            mockClipboard();
            renderIdle({
                result: { ...fakeExecutionResult(), [target]: text },
            });
            await waitFor(() => expect(screen.getByLabelText(ariaLabel)).toBeInTheDocument());
            await user.click(screen.getByLabelText(ariaLabel));
            expect(writeTextMock).toHaveBeenCalledWith(text);
            expect(toast.success).toHaveBeenCalledWith(`${toastLabel} copied to clipboard`);
        });

        it('shows error toast when clipboard write fails', async () => {
            mockClipboard(false);
            renderIdle({ result: { ...fakeExecutionResult(), stdout: 'x' } });
            await waitFor(() => expect(screen.getByLabelText('Copy output to clipboard')).toBeInTheDocument());
            await user.click(screen.getByLabelText('Copy output to clipboard'));
            expect(toast.error).toHaveBeenCalledWith('Failed to copy output');
        });
    });

    describe('render priority', () => {
        it('spinner takes priority over result', () => {
            renderIdle({
                phase: 'running' as ExecutionPhase,
                result: { ...fakeExecutionResult(), stdout: 'data' },
            });
            expect(screen.getByText('Running...')).toBeInTheDocument();
            expect(screen.queryByText('Stdout')).not.toBeInTheDocument();
        });

        it('result takes priority over error', async () => {
            renderIdle({
                result: { ...fakeExecutionResult(), status: 'error' },
                error: 'Something went wrong',
            });
            expect(await screen.findByText('error')).toHaveClass('badge-danger');
            expect(screen.queryByText('Execution Failed')).not.toBeInTheDocument();
        });
    });
});
