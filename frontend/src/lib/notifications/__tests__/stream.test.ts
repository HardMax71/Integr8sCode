import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';
import { notificationStreamApiV1EventsNotificationsStreamGet, type NotificationResponse } from '#lib/api/index.ts';
import { notificationStream } from '#lib/notifications/stream.svelte.ts';
import { fakeNotificationResponse } from '#lib/api/@faker-js/faker.gen.ts';
import { captureLogs, mockStreamEvents } from '#test/test-utils.ts';

type StreamOptions = NonNullable<Parameters<typeof notificationStreamApiV1EventsNotificationsStreamGet>[0]>;

const mockSseFn = vi.mocked(notificationStreamApiV1EventsNotificationsStreamGet);

const payload = (): NotificationResponse => ({
    ...fakeNotificationResponse(),
    notification_id: 'n-1',
    channel: 'in_app',
    severity: 'medium',
    subject: 'Test',
    body: 'Hello',
    action_url: '/action',
    tags: ['tag1'],
});

function mockOpenStream(): void {
    mockSseFn.mockImplementation(async () => ({
        // stays open until aborted
        stream: (async function* () {
            await new Promise<never>(() => {});
        })(),
    }));
}

const options = (call: number): StreamOptions => mockSseFn.mock.calls[call]![0]!;

describe('NotificationStream', () => {
    let callback: Mock<(data: NotificationResponse) => void>;

    beforeEach(() => {
        callback = vi.fn<(data: NotificationResponse) => void>();
        notificationStream.disconnect();
    });

    it('calls callback with each notification from the stream', async () => {
        mockStreamEvents(mockSseFn, payload());
        notificationStream.connect(callback);

        await vi.waitFor(() => expect(callback).toHaveBeenCalledOnce());
        expect(callback.mock.calls[0]![0]).toMatchObject({
            notification_id: 'n-1',
            channel: 'in_app',
            subject: 'Test',
            body: 'Hello',
            severity: 'medium',
        });
    });

    it('fires browser Notification when permission is granted', async () => {
        const MockNotification = vi.fn();
        Object.defineProperty(MockNotification, 'permission', { value: 'granted' });
        vi.stubGlobal('Notification', MockNotification);

        mockStreamEvents(mockSseFn, payload());
        notificationStream.connect(callback);

        await vi.waitFor(() =>
            expect(MockNotification).toHaveBeenCalledWith('Test', { body: 'Hello', icon: '/favicon.png' }),
        );
    });

    it('passes abort signal to SSE client', () => {
        mockOpenStream();
        notificationStream.connect(callback);

        const signal = options(0).signal!;
        expect(signal.aborted).toBe(false);

        notificationStream.disconnect();
        expect(signal.aborted).toBe(true);
    });

    it('aborts previous connection on reconnect', () => {
        mockOpenStream();
        notificationStream.connect(callback);

        const firstSignal = options(0).signal!;

        mockOpenStream();
        notificationStream.connect(callback);

        expect(firstSignal.aborted).toBe(true);
        expect(mockSseFn).toHaveBeenCalledTimes(2);
    });

    it('logs a lost connection, but not the abort of its own disconnect', () => {
        const records = captureLogs();
        mockOpenStream();
        notificationStream.connect(callback);
        const error = new TypeError('Failed to fetch');

        options(0).onSseError!(error);
        notificationStream.disconnect();
        options(0).onSseError!(new DOMException('The operation was aborted.', 'AbortError'));

        expect(records).toEqual([
            expect.objectContaining({
                level: 'warning',
                category: ['integr8scode', 'notifications'],
                message: ['Notification stream lost its connection: ', error, ''],
            }),
        ]);
    });

    it('configures SSE retry options', () => {
        mockOpenStream();
        notificationStream.connect(callback);

        expect(options(0)).toMatchObject({
            sseMaxRetryAttempts: 3,
            sseDefaultRetryDelay: 5000,
            sseMaxRetryDelay: 20000,
        });
    });
});
