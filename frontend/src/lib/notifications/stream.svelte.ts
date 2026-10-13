import { notificationStreamApiV1EventsNotificationsStreamGet, type NotificationResponse } from '#lib/api/index.ts';
import { getLogger } from '@logtape/logtape';

const log = getLogger(['integr8scode', 'notifications']);

type NotificationCallback = (data: NotificationResponse) => void;

class NotificationStream {
    #abortController: AbortController | null = null;

    connect(onNotification: NotificationCallback): void {
        this.disconnect();
        const controller = new AbortController();
        this.#abortController = controller;
        void this.#start(onNotification, controller.signal).catch((err: unknown) => {
            log.error('Notification stream stopped: {error}', { error: err });
        });
    }

    async #start(onNotification: NotificationCallback, signal: AbortSignal): Promise<void> {
        const { stream } = await notificationStreamApiV1EventsNotificationsStreamGet({
            signal,
            onSseError: (error) => {
                if (!signal.aborted) log.warning('Notification stream lost its connection: {error}', { error });
            },
            sseMaxRetryAttempts: 3,
            sseDefaultRetryDelay: 5000,
            sseMaxRetryDelay: 20000,
        });

        for await (const data of stream) {
            onNotification(data);

            if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
                new Notification(data.subject, { body: data.body, icon: '/favicon.png' });
            }
        }
    }

    disconnect(): void {
        this.#abortController?.abort();
        this.#abortController = null;
    }
}

export const notificationStream = new NotificationStream();
