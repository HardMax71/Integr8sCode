/**
 * Auto-refresh state factory for admin pages
 * Manages interval-based data reloading with configurable rates
 */

import { onDestroy } from 'svelte';

export interface AutoRefreshState {
    enabled: boolean;
    rate: number;
    readonly rateOptions: RefreshRateOption[];
    start: () => void;
    stop: () => void;
    restart: () => void;
    cleanup: () => void;
}

export interface RefreshRateOption {
    value: number;
    label: string;
}

export interface AutoRefreshOptions {
    initialEnabled?: boolean;
    initialRate?: number;
    rateOptions?: RefreshRateOption[];
    onRefresh: () => void | Promise<void>;
    autoCleanup?: boolean;
}

const DEFAULT_RATE_OPTIONS: RefreshRateOption[] = [
    { value: 5, label: '5 seconds' },
    { value: 10, label: '10 seconds' },
    { value: 30, label: '30 seconds' },
    { value: 60, label: '1 minute' }
];

const DEFAULT_OPTIONS = {
    initialEnabled: true,
    initialRate: 5,
    rateOptions: DEFAULT_RATE_OPTIONS,
    autoCleanup: true
};

/**
 * Creates reactive auto-refresh state with interval management
 * @example
 * const autoRefresh = createAutoRefresh({
 *     onRefresh: loadData,
 *     initialRate: 10
 * });
 */
export function createAutoRefresh(options: AutoRefreshOptions): AutoRefreshState {
    const opts = { ...DEFAULT_OPTIONS, ...options };

    let enabled = $state(opts.initialEnabled);
    let rate = $state(opts.initialRate);
    let interval: ReturnType<typeof setInterval> | null = null;

    function start(): void {
        stop();
        if (enabled) {
            interval = setInterval(opts.onRefresh, rate * 1000);
        }
    }

    function stop(): void {
        if (interval) {
            clearInterval(interval);
            interval = null;
        }
    }

    function restart(): void {
        start();
    }

    function cleanup(): void {
        stop();
    }

    // Auto-cleanup on component destroy if enabled
    if (opts.autoCleanup) {
        onDestroy(cleanup);
    }

    // Watch for changes to enabled/rate and restart
    $effect(() => {
        void enabled;
        void rate;
        start();
        return () => stop();
    });

    return {
        get enabled() { return enabled; },
        set enabled(v: boolean) { enabled = v; },
        get rate() { return rate; },
        set rate(v: number) { rate = v; },
        get rateOptions() { return opts.rateOptions; },
        start,
        stop,
        restart,
        cleanup
    };
}
