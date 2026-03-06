export function pollWhileVisible(fn: () => void | Promise<void>, intervalMs: number): void {
    $effect(() => {
        let id: ReturnType<typeof setInterval> | null = null;

        function start() {
            if (!id) id = setInterval(fn, intervalMs);
        }

        function stop() {
            if (id) {
                clearInterval(id);
                id = null;
            }
        }

        function onVisibility() {
            if (document.hidden) {
                stop();
            } else {
                start();
            }
        }

        document.addEventListener('visibilitychange', onVisibility);
        if (!document.hidden) start();

        return () => {
            stop();
            document.removeEventListener('visibilitychange', onVisibility);
        };
    });
}
