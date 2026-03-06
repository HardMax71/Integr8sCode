<script lang="ts">
    import { onMount } from 'svelte';
    import type { ExecutionResult } from '$lib/api';
    import type { ExecutionPhase } from '$lib/editor';
    import Spinner from '$components/Spinner.svelte';
    import { AlertTriangle, FileText, Copy } from '@lucide/svelte';
    import { toast } from 'svelte-sonner';

    let {
        phase,
        result,
        error,
    }: {
        phase: ExecutionPhase;
        result: ExecutionResult | null;
        error: string | null;
    } = $props();

    let ansiConverter = $state<import('ansi_up').AnsiUp | null>(null);
    let purify = $state<typeof import('dompurify').default | null>(null);
    let depsReady = $state(false);

    async function ensureDeps() {
        if (!ansiConverter) {
            const [{ AnsiUp }, dp] = await Promise.all([import('ansi_up'), import('dompurify')]);
            ansiConverter = new AnsiUp();
            ansiConverter.use_classes = true;
            ansiConverter.escape_html = true;
            purify = dp.default;
        }
        depsReady = true;
    }

    onMount(() => {
        ensureDeps();
    });

    function sanitize(html: string): string {
        return purify!.sanitize(html, {
            ALLOWED_TAGS: ['span', 'br', 'div'],
            ALLOWED_ATTR: ['class'],
        });
    }

    async function copyToClipboard(text: string, label: string) {
        try {
            await navigator.clipboard.writeText(text);
            toast.success(`${label} copied to clipboard`);
        } catch {
            toast.error(`Failed to copy ${label.toLowerCase()}`);
        }
    }

    const statusClasses = $derived.by(() => {
        if (!result) return '';
        const s = result.status;
        if (s === 'completed')
            return 'bg-green-50 text-green-700 ring-green-600 dark:bg-green-950 dark:text-green-300 dark:ring-green-500';
        if (s === 'error' || s === 'failed')
            return 'bg-red-50 text-red-700 ring-red-600 dark:bg-red-950 dark:text-red-300 dark:ring-red-500';
        if (s === 'running')
            return 'bg-blue-50 text-blue-700 ring-blue-600 dark:bg-blue-950 dark:text-blue-300 dark:ring-blue-500';
        if (s === 'queued')
            return 'bg-yellow-50 text-yellow-700 ring-yellow-600 dark:bg-yellow-950 dark:text-yellow-300 dark:ring-yellow-500';
        return '';
    });

    const phaseLabel = $derived.by(() => {
        if (phase === 'starting') return 'Starting...';
        if (phase === 'queued') return 'Queued...';
        if (phase === 'scheduled') return 'Scheduled...';
        if (phase === 'running') return 'Running...';
        return 'Executing...';
    });
</script>

<div class="output-container flex flex-col h-full">
    <h3
        class="text-base font-medium text-fg-default dark:text-dark-fg-default mb-3 border-b border-border-default dark:border-dark-border-default pb-3 shrink-0"
    >
        Execution Output
    </h3>
    <div class="output-content flex-grow overflow-auto pr-2 text-sm custom-scrollbar">
        {#if phase !== 'idle'}
            <div class="flex flex-col items-center justify-center h-full text-center p-4 animate-fade-in">
                <Spinner />
                <p class="mt-3 text-sm font-medium text-primary-dark dark:text-primary-light">{phaseLabel}</p>
            </div>
        {:else if error && !result}
            <div class="flex flex-col items-center justify-center h-full text-center p-4 animate-fade-in">
                <div class="w-12 h-12 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center mb-3">
                    <AlertTriangle class="w-6 h-6 text-red-600 dark:text-red-400" />
                </div>
                <p class="text-sm font-medium text-red-700 dark:text-red-300">Execution Failed</p>
                <p class="mt-1 text-xs text-fg-muted dark:text-dark-fg-muted max-w-xs">{error}</p>
            </div>
        {:else if result && depsReady}
            <div class="space-y-5 animate-fly-in">
                <div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs">
                    <span
                        class="inline-flex items-center rounded-lg px-2 py-1 font-medium ring-1 ring-inset whitespace-nowrap {statusClasses}"
                    >
                        Status: {result.status}
                    </span>

                    {#if result.execution_id}
                        <div class="relative group">
                            <button
                                type="button"
                                class="inline-flex items-center p-1.5 rounded-lg text-fg-muted dark:text-dark-fg-muted hover:text-fg-default dark:hover:text-dark-fg-default hover:bg-neutral-100 dark:hover:bg-neutral-700 transition-colors duration-150 cursor-pointer"
                                aria-label="Click to copy execution ID"
                                onclick={() => copyToClipboard(result!.execution_id, 'Execution ID')}
                            >
                                <FileText class="w-4 h-4" />
                            </button>
                            <div
                                class="absolute top-8 right-0 z-10 px-2 py-1 text-xs bg-neutral-800 dark:bg-neutral-200 text-white dark:text-neutral-800 rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none whitespace-nowrap"
                            >
                                Execution ID: <br />{result.execution_id}<br /><span class="text-xs opacity-75"
                                    >Click to copy</span
                                >
                            </div>
                        </div>
                    {/if}
                </div>

                {#if result.stdout}
                    <div class="output-section">
                        <h4
                            class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1 uppercase tracking-wider"
                        >
                            Output:
                        </h4>
                        <div class="relative">
                            <pre class="output-pre custom-scrollbar" data-testid="output-pre">{@html sanitize(
                                    ansiConverter!.ansi_to_html(result.stdout),
                                )}</pre>
                            <div class="absolute bottom-2 right-2 group">
                                <button
                                    type="button"
                                    class="inline-flex items-center p-1.5 rounded-lg text-fg-muted dark:text-dark-fg-muted hover:text-fg-default dark:hover:text-dark-fg-default hover:bg-neutral-100 dark:hover:bg-neutral-700 transition-colors duration-150 cursor-pointer opacity-70 hover:opacity-100"
                                    aria-label="Copy output to clipboard"
                                    onclick={() => copyToClipboard(result!.stdout!, 'Output')}
                                >
                                    <Copy class="w-4 h-4" />
                                </button>
                                <div
                                    class="absolute bottom-8 right-0 z-10 px-2 py-1 text-xs bg-neutral-800 dark:bg-neutral-200 text-white dark:text-neutral-800 rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none whitespace-nowrap"
                                >
                                    Copy output
                                </div>
                            </div>
                        </div>
                    </div>
                {/if}

                {#if result.stderr}
                    <div class="error-section">
                        <h4 class="text-xs font-medium text-red-700 dark:text-red-300 mb-1 uppercase tracking-wider">
                            Errors:
                        </h4>
                        <div class="relative">
                            <div
                                class="p-3 rounded-lg bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800"
                            >
                                <pre
                                    class="text-xs text-red-600 dark:text-red-300 whitespace-pre-wrap break-words font-mono bg-transparent p-0 pr-8">{@html sanitize(
                                        ansiConverter!.ansi_to_html(result.stderr),
                                    )}</pre>
                            </div>
                            <div class="absolute bottom-2 right-2 group">
                                <button
                                    type="button"
                                    class="inline-flex items-center p-1.5 rounded-lg text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-200 hover:bg-red-100 dark:hover:bg-red-900 transition-colors duration-150 cursor-pointer opacity-70 hover:opacity-100"
                                    aria-label="Copy error text to clipboard"
                                    onclick={() => copyToClipboard(result!.stderr!, 'Error text')}
                                >
                                    <Copy class="w-4 h-4" />
                                </button>
                                <div
                                    class="absolute bottom-8 right-0 z-10 px-2 py-1 text-xs bg-neutral-800 dark:bg-neutral-200 text-white dark:text-neutral-800 rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none whitespace-nowrap"
                                >
                                    Copy errors
                                </div>
                            </div>
                        </div>
                    </div>
                {/if}

                {#if result.resource_usage}
                    {@const clkTck = result.resource_usage.clk_tck_hertz}
                    {@const cpuMs = (result.resource_usage.cpu_time_jiffies * 1000) / clkTck}
                    <div
                        class="p-3 rounded-lg bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800 text-xs space-y-1"
                    >
                        <h4 class="text-xs font-medium text-blue-700 dark:text-blue-300 mb-2 uppercase tracking-wider">
                            Resource Usage:
                        </h4>
                        <div class="grid grid-cols-1 sm:grid-cols-3 gap-x-3 gap-y-1">
                            <div class="flex flex-col">
                                <span class="text-fg-muted dark:text-dark-fg-muted font-normal">CPU:</span>
                                <span class="text-fg-default dark:text-dark-fg-default font-medium">
                                    {result.resource_usage.cpu_time_jiffies === 0
                                        ? `< ${(1000 / clkTck).toFixed(0)} m`
                                        : `${cpuMs.toFixed(3)} m`}
                                </span>
                            </div>
                            <div class="flex flex-col">
                                <span class="text-fg-muted dark:text-dark-fg-muted font-normal">Memory:</span>
                                <span class="text-fg-default dark:text-dark-fg-default font-medium">
                                    {`${(result.resource_usage.peak_memory_kb / 1024).toFixed(3)} MiB`}
                                </span>
                            </div>
                            <div class="flex flex-col">
                                <span class="text-fg-muted dark:text-dark-fg-muted font-normal">Time:</span>
                                <span class="text-fg-default dark:text-dark-fg-default font-medium">
                                    {`${result.resource_usage.execution_time_wall_seconds.toFixed(3)} s`}
                                </span>
                            </div>
                        </div>
                    </div>
                {/if}
            </div>
        {:else}
            <div
                class="flex items-center justify-center h-full text-center text-fg-muted dark:text-dark-fg-muted italic p-4"
            >
                Write some code and click "Run Script" to see the output.
            </div>
        {/if}
    </div>
</div>
