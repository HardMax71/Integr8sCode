import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { effect_root } from 'svelte/internal/client';

// Mock onDestroy — no component lifecycle in unit tests
vi.mock('svelte', async (importOriginal) => {
    const actual = await importOriginal<typeof import('svelte')>();
    return { ...actual, onDestroy: vi.fn() };
});

const { createAutoRefresh } = await import('../autoRefresh.svelte');

describe('createAutoRefresh', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    function make(overrides: Record<string, unknown> = {}) {
        const onRefresh = vi.fn();
        let ar!: ReturnType<typeof createAutoRefresh>;
        const teardown = effect_root(() => {
            ar = createAutoRefresh({
                onRefresh,
                autoCleanup: false,
                initialEnabled: false,
                ...overrides,
            });
        });
        return { ar, onRefresh, teardown };
    }

    describe('initial state', () => {
        it.each([
            [{ initialEnabled: true }, true],
            [{ initialEnabled: false }, false],
        ])('enabled=%j → %s', (opts, expected) => {
            const { ar, teardown } = make(opts);
            expect(ar.enabled).toBe(expected);
            ar.cleanup();
            teardown();
        });

        it('defaults rate to 5', () => {
            const { ar, teardown } = make();
            expect(ar.rate).toBe(5);
            ar.cleanup();
            teardown();
        });

        it('exposes default rate options', () => {
            const { ar, teardown } = make();
            expect(ar.rateOptions).toEqual([
                { value: 5, label: '5 seconds' },
                { value: 10, label: '10 seconds' },
                { value: 30, label: '30 seconds' },
                { value: 60, label: '1 minute' },
            ]);
            ar.cleanup();
            teardown();
        });

        it('accepts custom rate options', () => {
            const custom = [{ value: 15, label: '15s' }];
            const { ar, teardown } = make({ rateOptions: custom });
            expect(ar.rateOptions).toEqual(custom);
            ar.cleanup();
            teardown();
        });
    });

    describe('start / stop / cleanup', () => {
        it('start fires onRefresh at the configured rate', () => {
            const { ar, onRefresh, teardown } = make({ initialRate: 2 });
            ar.enabled = true;
            ar.start();

            vi.advanceTimersByTime(2000);
            expect(onRefresh).toHaveBeenCalledTimes(1);

            vi.advanceTimersByTime(2000);
            expect(onRefresh).toHaveBeenCalledTimes(2);

            ar.cleanup();
            teardown();
        });

        it('does not fire when disabled', () => {
            const { ar, onRefresh, teardown } = make({ initialEnabled: false });
            ar.start();

            vi.advanceTimersByTime(10_000);
            expect(onRefresh).not.toHaveBeenCalled();

            ar.cleanup();
            teardown();
        });

        it('stop halts the interval', () => {
            const { ar, onRefresh, teardown } = make({ initialRate: 1 });
            ar.enabled = true;
            ar.start();

            vi.advanceTimersByTime(1000);
            expect(onRefresh).toHaveBeenCalledTimes(1);

            ar.stop();
            vi.advanceTimersByTime(5000);
            expect(onRefresh).toHaveBeenCalledTimes(1);

            teardown();
        });

        it('restart restarts the interval', () => {
            const { ar, onRefresh, teardown } = make({ initialRate: 1 });
            ar.enabled = true;
            ar.start();

            vi.advanceTimersByTime(500);
            ar.restart(); // resets timer
            vi.advanceTimersByTime(500);
            expect(onRefresh).not.toHaveBeenCalled(); // only 500ms since restart

            vi.advanceTimersByTime(500);
            expect(onRefresh).toHaveBeenCalledTimes(1);

            ar.cleanup();
            teardown();
        });

        it('cleanup stops the interval', () => {
            const { ar, onRefresh, teardown } = make({ initialRate: 1 });
            ar.enabled = true;
            ar.start();

            ar.cleanup();
            vi.advanceTimersByTime(5000);
            expect(onRefresh).not.toHaveBeenCalled();

            teardown();
        });
    });
});
