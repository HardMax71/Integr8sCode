import { describe, expect, it } from 'vitest';
import {
    browseEventsApiV1AdminEventsBrowsePostResponseTransformer,
    getEventDetailApiV1AdminEventsEventIdGetResponseTransformer,
    getExecutionEventsApiV1ExecutionsExecutionIdEventsGetResponseTransformer,
} from '#lib/api/transformers.gen.ts';

// Stock hey-api 0.99 skips discriminated unions; these fail if the client is generated without patches/
const AT = '2026-10-11T08:00:00Z';

const rawEvents = (): Record<string, unknown>[] => [
    { event_type: 'execution_requested', timestamp: AT, execution_id: 'e1' },
    { event_type: 'execution_queued', timestamp: AT, estimated_start_time: AT },
    { event_type: 'notification_sent', timestamp: AT, sent_at: AT },
    { event_type: 'saga_cancelled', timestamp: AT, cancelled_at: AT },
];

const withDates = (event: Record<string, unknown>) =>
    Object.fromEntries(Object.entries(event).map(([key, value]) => [key, value === AT ? new Date(AT) : value]));

describe('generated transformers for the event union', () => {
    it('converts the dates of each event type in the browse list', async () => {
        const response = await browseEventsApiV1AdminEventsBrowsePostResponseTransformer({
            events: rawEvents(),
            total: 4,
            skip: 0,
            limit: 10,
        });

        expect(response.events).toEqual(rawEvents().map(withDates));
    });

    it('converts the dates of each event type in the per-execution list', async () => {
        const events = await getExecutionEventsApiV1ExecutionsExecutionIdEventsGetResponseTransformer(rawEvents());

        expect(events).toEqual(rawEvents().map(withDates));
    });

    it.each(rawEvents().map((event) => [event.event_type, event]))(
        'converts the dates of a %s event in the detail',
        async (_type, event) => {
            const detail = await getEventDetailApiV1AdminEventsEventIdGetResponseTransformer({
                event: { ...event },
                related_events: [],
                timeline: [],
            });

            expect(detail.event).toEqual(withDates(event));
        },
    );
});
