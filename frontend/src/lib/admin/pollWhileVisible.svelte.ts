function sleep(ms: number, signal: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
        const id = setTimeout(resolve, ms);
        signal.addEventListener(
            'abort',
            () => {
                clearTimeout(id);
                reject(new Error('aborted'));
            },
            { once: true },
        );
    });
}

export function pollWhileVisible(fn: () => void | Promise<void>, intervalMs: number | (() => number)): void {
    $effect(() => {
        const ms = typeof intervalMs === 'function' ? intervalMs() : intervalMs;
        const ac = new AbortController();

        async function run() {
            while (!ac.signal.aborted) {
                await sleep(ms, ac.signal);
                if (!document.hidden) await fn();
            }
        }

        run().catch(() => {});

        return () => {
            ac.abort();
        };
    });
}
