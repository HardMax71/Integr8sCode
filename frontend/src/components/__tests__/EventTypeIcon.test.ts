import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';
import { EventType } from '#lib/api/index.ts';
import EventTypeIcon from '#components/EventTypeIcon.svelte';

const iconOf = (eventType: EventType) =>
    render(EventTypeIcon, { props: { eventType } }).container.querySelector('svg')?.innerHTML;

describe('EventTypeIcon', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    describe('event types with their own icon', () => {
        it.each([
            EventType.EXECUTION_REQUESTED,
            EventType.EXECUTION_STARTED,
            EventType.EXECUTION_COMPLETED,
            EventType.EXECUTION_FAILED,
            EventType.EXECUTION_TIMEOUT,
            EventType.POD_CREATED,
            EventType.POD_RUNNING,
            EventType.POD_SUCCEEDED,
            EventType.POD_FAILED,
            EventType.POD_TERMINATED,
        ])('renders a specific icon for %s', (eventType) => {
            expect(iconOf(eventType)).toBeDefined();
            expect(iconOf(eventType)).not.toBe(iconOf(EventType.USER_SETTINGS_UPDATED));
        });
    });

    describe('other event types', () => {
        it('renders the fallback icon', () => {
            const { container } = render(EventTypeIcon, { props: { eventType: EventType.USER_SETTINGS_UPDATED } });
            expect(container.querySelector('svg')).toBeInTheDocument();
        });
    });

    describe('size prop', () => {
        it.each([
            { size: undefined, expected: '20', desc: 'defaults to 20' },
            { size: 32, expected: '32', desc: 'passes custom size' },
        ])('$desc', ({ size, expected }) => {
            const { container } = render(EventTypeIcon, {
                props: { eventType: EventType.EXECUTION_STARTED, ...(size ? { size } : {}) },
            });
            const svg = container.querySelector('svg');
            expect(svg).toHaveAttribute('width', expected);
            expect(svg).toHaveAttribute('height', expected);
        });
    });
});
