import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { toast } from 'svelte-sonner';
import { mockStreamEvents, user } from '#test/test-utils.ts';
import {
    ExecutionStatus,
    ReplayStatus,
    streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet,
    type EventReplayStatusResponse,
} from '#lib/api/index.ts';

import {
    fakeEventReplayStatusResponse,
    fakeExecutionResult,
    fakeReplayError,
    fakeResourceUsage,
} from '#lib/api/@faker-js/faker.gen.ts';
import ReplayProgressBanner from '#components/admin/events/ReplayProgressBanner.svelte';

function makeSession(overrides: Partial<EventReplayStatusResponse> = {}): EventReplayStatusResponse {
    return {
        ...fakeEventReplayStatusResponse(),
        status: ReplayStatus.RUNNING,
        total_events: 10,
        replayed_events: 5,
        progress_percentage: 50,
        errors: null,
        execution_results: null,
        ...overrides,
    };
}

async function renderBanner(...statuses: EventReplayStatusResponse[]) {
    mockStreamEvents(streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet, ...statuses);
    const onClose = vi.fn();
    const result = render(ReplayProgressBanner, { props: { sessionId: 'session-1', onClose } });
    await screen.findByText('Replay in Progress');
    return { ...result, onClose };
}

describe('ReplayProgressBanner', () => {
    it('follows the stream of the session it was given', async () => {
        await renderBanner(makeSession());
        expect(vi.mocked(streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet)).toHaveBeenCalledWith(
            expect.objectContaining({ path: { session_id: 'session-1' } }),
        );
    });

    it('renders nothing before the first status arrives', () => {
        vi.mocked(streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet).mockReturnValue(
            new Promise<never>(() => {}),
        );
        const { container } = render(ReplayProgressBanner, { props: { sessionId: 'session-1', onClose: vi.fn() } });
        expect(container.textContent?.trim()).toBe('');
    });

    it('shows the latest status the stream sent', async () => {
        await renderBanner(
            makeSession({ replayed_events: 2 }),
            makeSession({ replayed_events: 9, progress_percentage: 90 }),
        );
        await waitFor(() => expect(screen.getByText('Progress: 9 / 10 events')).toBeInTheDocument());
    });

    it.each([
        {
            status: ReplayStatus.COMPLETED,
            notice: 'success',
            text: 'Replay completed! Processed 5 events successfully.',
        },
        { status: ReplayStatus.FAILED, notice: 'error', text: 'Replay failed: boom' },
    ] as const)('toasts when the replay ends as $status', async ({ status, notice, text }) => {
        await renderBanner(makeSession({ status, errors: [{ ...fakeReplayError(), error: 'boom' }] }));
        await waitFor(() => expect(toast[notice]).toHaveBeenCalledWith(text));
    });

    it('stops following the stream when it unmounts', async () => {
        const { unmount } = await renderBanner(makeSession());
        const [options] = vi.mocked(streamReplayStatusApiV1AdminEventsReplaySessionIdStatusGet).mock.calls[0]!;
        unmount();
        expect(options.signal?.aborted).toBe(true);
    });

    it('shows title and status', async () => {
        await renderBanner(makeSession({ status: ReplayStatus.RUNNING }));
        expect(screen.getByText('Replay in Progress')).toBeInTheDocument();
        expect(screen.getByText('running')).toBeInTheDocument();
    });

    it('shows progress text and percentage', async () => {
        await renderBanner(makeSession({ replayed_events: 7, total_events: 20, progress_percentage: 35 }));
        expect(screen.getByText('Progress: 7 / 20 events')).toBeInTheDocument();
        expect(screen.getByText('35%')).toBeInTheDocument();
    });

    it('calls onClose when close button is clicked', async () => {
        const { onClose } = await renderBanner(makeSession());
        await user.click(screen.getByTitle('Close'));
        expect(onClose).toHaveBeenCalledOnce();
    });

    describe('errors', () => {
        it('hides error section when no errors', async () => {
            await renderBanner(makeSession({ errors: [] }));
            expect(screen.queryByText(/error/i)).not.toBeInTheDocument();
        });

        it('shows errors with event_id and error message', async () => {
            await renderBanner(
                makeSession({
                    errors: [
                        { ...fakeReplayError(), event_id: 'err-evt-1', error: 'Timeout exceeded' },
                        { ...fakeReplayError(), error: 'Connection refused' },
                    ],
                }),
            );
            expect(screen.getByText('err-evt-1')).toBeInTheDocument();
            expect(screen.getByText('Timeout exceeded')).toBeInTheDocument();
            expect(screen.getByText('Connection refused')).toBeInTheDocument();
        });
    });

    describe('execution results', () => {
        it('hides execution results section when not present', async () => {
            await renderBanner(makeSession());
            expect(screen.queryByText('Execution Results')).not.toBeInTheDocument();
        });

        it('shows execution results with status badges and execution_id', async () => {
            await renderBanner(
                makeSession({
                    execution_results: [
                        {
                            ...fakeExecutionResult(),
                            execution_id: 'exec-r1',
                            status: ExecutionStatus.COMPLETED,
                            stdout: 'hello',
                            resource_usage: { ...fakeResourceUsage(), execution_time_wall_seconds: 1.23 },
                        },
                    ],
                }),
            );
            expect(screen.getByRole('heading', { name: 'Execution Results' })).toBeInTheDocument();
            expect(screen.getByText('exec-r1')).toBeInTheDocument();
            expect(screen.getByText('completed')).toBeInTheDocument();
            expect(screen.getByText('1.23s')).toBeInTheDocument();
            expect(screen.getByText('hello')).toBeInTheDocument();
        });

        it('shows stderr in red when present', async () => {
            await renderBanner(
                makeSession({
                    execution_results: [
                        {
                            ...fakeExecutionResult(),
                            execution_id: 'exec-err',
                            status: ExecutionStatus.FAILED,
                            stderr: 'NameError',
                            exit_code: 1,
                        },
                    ],
                }),
            );
            expect(screen.getByText('NameError')).toBeInTheDocument();
        });
    });
});
