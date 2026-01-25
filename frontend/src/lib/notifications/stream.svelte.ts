import { EventSourcePlus } from 'event-source-plus';
import type { NotificationResponse, SseNotificationEventData } from '$lib/api';

type NotificationCallback = (data: NotificationResponse) => void;

// Validates SSE notification has all required fields for UI
function isCompleteNotification(data: SseNotificationEventData): boolean {
    return !!(data.notification_id && data.subject && data.body && data.status && data.created_at);
}

class NotificationStream {
    #controller: ReturnType<EventSourcePlus['listen']> | null = null;
    #onNotification: NotificationCallback | null = null;

    connected = $state(false);
    error = $state<string | null>(null);

    connect(onNotification: NotificationCallback): void {
        this.disconnect();
        this.#onNotification = onNotification;
        this.error = null;

        const sse = new EventSourcePlus('/api/v1/events/notifications/stream', {
            maxRetryCount: 3,
            maxRetryInterval: 20000,
            headers: {
                'Accept': 'text/event-stream',
            },
        });

        this.#controller = sse.listen({
            onResponse: () => {
                this.connected = true;
                this.error = null;
                console.log('Notification stream connected');
            },
            onMessage: (event) => {
                try {
                    const data: SseNotificationEventData = JSON.parse(event.data);

                    // Only process actual notification events with complete data
                    if (data.event_type === 'notification' && isCompleteNotification(data)) {
                        // SSE data matches NotificationResponse except 'channel' (unused by UI)
                        this.#onNotification?.(data as unknown as NotificationResponse);

                        if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
                            new Notification(data.subject!, { body: data.body!, icon: '/favicon.png' });
                        }
                    }
                } catch (err) {
                    console.error('Error processing notification:', err);
                }
            },
            onRequestError: ({ error }) => {
                console.error('Notification stream request error:', error);
                this.connected = false;
                this.error = error?.message ?? 'Connection failed';
            },
            onResponseError: ({ response }) => {
                console.error('Notification stream response error:', response.status);
                this.connected = false;
                if (response.status === 401) {
                    this.error = 'Unauthorized';
                    this.disconnect();
                }
            },
        });
    }

    disconnect(): void {
        this.#controller?.abort();
        this.#controller = null;
        this.#onNotification = null;
        this.connected = false;
    }
}

export const notificationStream = new NotificationStream();
