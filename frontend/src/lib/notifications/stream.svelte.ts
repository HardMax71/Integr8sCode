import { EventSourcePlus } from 'event-source-plus';
import type { NotificationResponse } from '$lib/api';

type NotificationCallback = (data: NotificationResponse) => void;

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
            onMessage: (message) => {
                if (message.event !== 'notification') return;
                try {
                    const data = JSON.parse(message.data) as NotificationResponse;
                    this.#onNotification?.(data);

                    if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
                        new Notification(data.subject, { body: data.body, icon: '/favicon.png' });
                    }
                } catch (err) {
                    console.error('Error processing notification:', err);
                }
            },
            onRequestError: ({ error }) => {
                console.error('Notification stream request error:', error);
                this.connected = false;
                this.error = (error as Error | null)?.message ?? 'Connection failed';
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
