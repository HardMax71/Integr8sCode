import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { NotificationResponse } from '$lib/api';

// Capture the listen callbacks so tests can invoke them directly
let listenCallbacks: Record<string, (...args: unknown[]) => void> = {};
const mockAbort = vi.fn();

vi.mock('event-source-plus', () => {
    const EventSourcePlus = function () {
        // noop constructor
    };
    EventSourcePlus.prototype.listen = function (cbs: Record<string, (...args: unknown[]) => void>) {
        listenCallbacks = cbs;
        return { abort: mockAbort };
    };
    return { EventSourcePlus };
});

// Must import after mocking
const { notificationStream } = await import('../stream.svelte');

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

describe('NotificationStream', () => {
    let callback: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        callback = vi.fn();
        listenCallbacks = {};
        mockAbort.mockClear();
        notificationStream.disconnect();
    });

    it('sets connected=true on onResponse', () => {
        notificationStream.connect(callback);
        listenCallbacks.onResponse!();
        expect(notificationStream.connected).toBe(true);
        expect(notificationStream.error).toBeNull();
    });

    it('calls callback with parsed NotificationResponse', () => {
        notificationStream.connect(callback);
        listenCallbacks.onMessage!({ event: 'notification', data: JSON.stringify(validPayload()) });

        expect(callback).toHaveBeenCalledOnce();
        const notification = callback.mock.calls[0][0];
        expect(notification).toMatchObject({
            notification_id: 'n-1',
            channel: 'in_app',
            status: 'delivered',
            subject: 'Test',
            body: 'Hello',
            read_at: null,
            severity: 'medium',
            tags: ['tag1'],
            action_url: '/action',
        });
    });

    it('ignores messages with non-notification event type', () => {
        notificationStream.connect(callback);
        listenCallbacks.onMessage!({ event: 'ping', data: '{}' });
        listenCallbacks.onMessage!({ event: '', data: '{}' });
        expect(callback).not.toHaveBeenCalled();
    });

    it('handles invalid JSON without crashing', () => {
        const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
        notificationStream.connect(callback);
        listenCallbacks.onMessage!({ event: 'notification', data: '{broken' });
        expect(callback).not.toHaveBeenCalled();
        expect(spy).toHaveBeenCalled();
        spy.mockRestore();
    });

    it('sets error on request error', () => {
        notificationStream.connect(callback);
        listenCallbacks.onResponse!();
        listenCallbacks.onRequestError!({ error: new Error('Network down') });
        expect(notificationStream.connected).toBe(false);
        expect(notificationStream.error).toBe('Network down');
    });

    it('falls back to "Connection failed" when error has no message', () => {
        notificationStream.connect(callback);
        listenCallbacks.onRequestError!({ error: null });
        expect(notificationStream.error).toBe('Connection failed');
    });

    it('disconnects on 401 response error', () => {
        notificationStream.connect(callback);
        listenCallbacks.onResponse!();
        listenCallbacks.onResponseError!({ response: { status: 401 } });
        expect(notificationStream.connected).toBe(false);
        expect(notificationStream.error).toBe('Unauthorized');
        expect(mockAbort).toHaveBeenCalled();
    });

    it('sets connected=false on non-401 response error', () => {
        notificationStream.connect(callback);
        listenCallbacks.onResponse!();
        listenCallbacks.onResponseError!({ response: { status: 500 } });
        expect(notificationStream.connected).toBe(false);
        expect(notificationStream.error).toBeNull();
    });

    it('disconnect aborts controller and resets state', () => {
        notificationStream.connect(callback);
        listenCallbacks.onResponse!();
        notificationStream.disconnect();
        expect(mockAbort).toHaveBeenCalled();
        expect(notificationStream.connected).toBe(false);
    });

    it('fires browser Notification when permission is granted', () => {
        const MockNotification = vi.fn();
        Object.defineProperty(MockNotification, 'permission', { value: 'granted' });
        vi.stubGlobal('Notification', MockNotification);

        notificationStream.connect(callback);
        listenCallbacks.onMessage!({ event: 'notification', data: JSON.stringify(validPayload()) });

        expect(MockNotification).toHaveBeenCalledWith('Test', { body: 'Hello', icon: '/favicon.png' });
        vi.unstubAllGlobals();
    });
});
