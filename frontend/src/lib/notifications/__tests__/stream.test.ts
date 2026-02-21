import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { NotificationResponse } from '$lib/api';

const mockSseFn = vi.fn();

vi.mock('$lib/api', () => ({
    notificationStreamApiV1EventsNotificationsStreamGet: mockSseFn,
}));

const { notificationStream } = await import('../stream.svelte');

const tick = () => new Promise(resolve => setTimeout(resolve, 0));

function validPayload(overrides: Partial<NotificationResponse> = {}): NotificationResponse {
    return {
        notification_id: 'n-1',
        channel: 'in_app',
        status: 'delivered',
        subject: 'Test',
        body: 'Hello',
        action_url: '/action',
        created_at: '2025-01-01T00:00:00Z',
        read_at: null,
        severity: 'medium',
        tags: ['tag1'],
        ...overrides,
    };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function mockStream(): { readonly onSseEvent: ((event: any) => void) | undefined } {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let onSseEvent: ((event: any) => void) | undefined;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mockSseFn.mockImplementation(async (options?: any) => {
        onSseEvent = options?.onSseEvent;
        return {
            stream: (async function* () {
                yield; // keep generator alive until aborted
                await new Promise<void>(() => {});
            })(),
        };
    });

    return { get onSseEvent() { return onSseEvent; } };
}

describe('NotificationStream', () => {
    let callback: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        callback = vi.fn();
        mockSseFn.mockReset();
        notificationStream.disconnect();
    });

    it('calls callback with parsed NotificationResponse', async () => {
        const mock = mockStream();
        notificationStream.connect(callback);
        await tick();

        mock.onSseEvent!({ event: 'notification', data: validPayload() });

        expect(callback).toHaveBeenCalledOnce();
        expect(callback.mock.calls[0][0]).toMatchObject({
            notification_id: 'n-1',
            channel: 'in_app',
            subject: 'Test',
            body: 'Hello',
            severity: 'medium',
        });
    });

    it('ignores non-notification events', async () => {
        const mock = mockStream();
        notificationStream.connect(callback);
        await tick();

        mock.onSseEvent!({ event: 'ping', data: {} });
        mock.onSseEvent!({ event: '', data: {} });
        mock.onSseEvent!({ data: {} });
        expect(callback).not.toHaveBeenCalled();
    });

    it('fires browser Notification when permission is granted', async () => {
        const MockNotification = vi.fn();
        Object.defineProperty(MockNotification, 'permission', { value: 'granted' });
        vi.stubGlobal('Notification', MockNotification);

        const mock = mockStream();
        notificationStream.connect(callback);
        await tick();

        mock.onSseEvent!({ event: 'notification', data: validPayload() });
        expect(MockNotification).toHaveBeenCalledWith('Test', { body: 'Hello', icon: '/favicon.png' });
        vi.unstubAllGlobals();
    });

    it('passes abort signal to SSE client', async () => {
        mockStream();
        notificationStream.connect(callback);
        await tick();

        const signal = mockSseFn.mock.calls[0][0].signal as AbortSignal;
        expect(signal.aborted).toBe(false);

        notificationStream.disconnect();
        expect(signal.aborted).toBe(true);
    });

    it('aborts previous connection on reconnect', async () => {
        mockStream();
        notificationStream.connect(callback);
        await tick();

        const firstSignal = mockSseFn.mock.calls[0][0].signal as AbortSignal;

        mockStream();
        notificationStream.connect(callback);
        await tick();

        expect(firstSignal.aborted).toBe(true);
        expect(mockSseFn).toHaveBeenCalledTimes(2);
    });

    it('configures SSE retry options', async () => {
        mockStream();
        notificationStream.connect(callback);
        await tick();

        const options = mockSseFn.mock.calls[0][0];
        expect(options.sseMaxRetryAttempts).toBe(3);
        expect(options.sseDefaultRetryDelay).toBe(5000);
        expect(options.sseMaxRetryDelay).toBe(20000);
    });
});
