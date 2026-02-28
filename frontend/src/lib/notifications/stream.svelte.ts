import {
    notificationStreamApiV1EventsNotificationsStreamGet,
    type NotificationResponse,
} from '$lib/api';
import { logger } from '$lib/logger';

const log = logger.withTag('NotificationStream');

type NotificationCallback = (data: NotificationResponse) => void;

class NotificationStream {
    #abortController: AbortController | null = null;

    connect(onNotification: NotificationCallback): void {
        this.disconnect();
        this.#abortController = new AbortController();
        void this.#start(onNotification).catch((err: unknown) => {
            log.error('Connection failed:', err);
        });
    }

    async #start(onNotification: NotificationCallback): Promise<void> {
        const { stream } = await notificationStreamApiV1EventsNotificationsStreamGet({
            signal: this.#abortController!.signal,
            sseMaxRetryAttempts: 3,
            sseDefaultRetryDelay: 5000,
            sseMaxRetryDelay: 20000,
            onSseEvent: (event) => {
                if (event.event !== 'notification') return;

                const data = event.data as NotificationResponse;
                onNotification(data);

                if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
                    new Notification(data.subject, { body: data.body, icon: '/favicon.png' });
                }
            },
        });

        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        for await (const _ of stream) { /* events dispatched via onSseEvent */ }
    }

    disconnect(): void {
        this.#abortController?.abort();
        this.#abortController = null;
    }
}

export const notificationStream = new NotificationStream();
