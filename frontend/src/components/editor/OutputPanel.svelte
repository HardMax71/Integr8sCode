<script lang="ts">
    import Anser from 'anser';
    import type { ExecutionResult } from '#lib/api/index.ts';
    import type { ExecutionPhase } from '#lib/editor/index.ts';
    import { fieldTitle } from '#lib/formatters.ts';
    import { EXECUTION_STATUS_BADGE } from '#lib/badges.ts';
    import Spinner from '#components/Spinner.svelte';
    import { TriangleAlert, FileText, Copy } from '@lucide/svelte';
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

    async function copyToClipboard(text: string, label: string) {
        try {
            await navigator.clipboard.writeText(text);
            toast.success(`${label} copied to clipboard`);
        } catch {
            toast.error(`Failed to copy ${label.toLowerCase()}`);
        }
    }

    const phaseLabel = $derived.by(() => {
        if (phase === 'starting') return 'Starting...';
        if (phase === 'queued') return 'Queued...';
        if (phase === 'scheduled') return 'Scheduled...';
        if (phase === 'running') return 'Running...';
        return 'Executing...';
    });
</script>

{#snippet ansi(
    text: string,
)}{#each Anser.ansiToJson(text, { use_classes: true, remove_empty: true }) as part, i (i)}<span
            class={[part.fg && `${part.fg}-fg`, part.bg && `${part.bg}-bg`, part.decorations.map((d) => `ansi-${d}`)]}
            >{part.content}</span
        >{/each}{/snippet}

{#snippet usageField(key: string, value: string | number)}
    <div class="flex flex-col">
        <dt class="text-fg-muted font-normal">{fieldTitle(key)}</dt>
        <dd class="text-fg font-medium">{value}</dd>
    </div>
{/snippet}

<div class="output-container flex flex-col h-full">
    <h3 class="text-base font-medium text-fg mb-3 border-b border-border pb-3 shrink-0">Execution Output</h3>
    <div class="output-content flex-grow overflow-auto pr-2 text-sm custom-scrollbar">
        {#if phase !== 'idle'}
            <div class="flex flex-col items-center justify-center h-full text-center p-4 animate-fade-in">
                <Spinner />
                <p class="mt-3 text-sm font-medium text-accent">{phaseLabel}</p>
            </div>
        {:else if error && !result}
            <div class="flex flex-col items-center justify-center h-full text-center p-4 animate-fade-in">
                <div class="w-12 h-12 rounded-full bg-danger-soft flex items-center justify-center mb-3">
                    <TriangleAlert class="w-6 h-6 text-danger" />
                </div>
                <p class="text-sm font-medium text-danger">Execution Failed</p>
                <p class="mt-1 text-xs text-fg-muted max-w-xs">{error}</p>
            </div>
        {:else if result}
            <div class="space-y-5 animate-fly-in">
                <div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs">
                    <span class="badge whitespace-nowrap {EXECUTION_STATUS_BADGE[result.status]}">
                        <span class="mr-1 opacity-75">{fieldTitle('status')}</span>{result.status}
                    </span>

                    {#if result.execution_id}
                        <div class="relative group">
                            <button
                                type="button"
                                class="inline-flex items-center p-1.5 rounded-lg text-fg-muted hover:text-fg hover:bg-muted transition-colors duration-150 cursor-pointer"
                                aria-label="Click to copy execution ID"
                                onclick={() => copyToClipboard(result!.execution_id, 'Execution ID')}
                            >
                                <FileText class="w-4 h-4" />
                            </button>
                            <div
                                class="absolute top-8 right-0 z-10 px-2 py-1 text-xs bg-tooltip text-white rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none whitespace-nowrap"
                            >
                                {fieldTitle('execution_id')}<br />{result.execution_id}<br /><span
                                    class="text-xs opacity-75">Click to copy</span
                                >
                            </div>
                        </div>
                    {/if}
                </div>

                {#if result.stdout}
                    <div class="output-section">
                        <h4 class="text-xs font-medium text-fg-muted mb-1 uppercase tracking-wider">
                            {fieldTitle('stdout')}
                        </h4>
                        <div class="relative">
                            <pre class="output-pre custom-scrollbar" data-testid="output-pre">{@render ansi(
                                    result.stdout,
                                )}</pre>
                            <div class="absolute bottom-2 right-2 group">
                                <button
                                    type="button"
                                    class="inline-flex items-center p-1.5 rounded-lg text-fg-muted hover:text-fg hover:bg-muted transition-colors duration-150 cursor-pointer opacity-70 hover:opacity-100"
                                    aria-label="Copy output to clipboard"
                                    onclick={() => copyToClipboard(result!.stdout!, 'Output')}
                                >
                                    <Copy class="w-4 h-4" />
                                </button>
                                <div
                                    class="absolute bottom-8 right-0 z-10 px-2 py-1 text-xs bg-tooltip text-white rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none whitespace-nowrap"
                                >
                                    Copy output
                                </div>
                            </div>
                        </div>
                    </div>
                {/if}

                {#if result.stderr}
                    <div class="error-section">
                        <h4 class="text-xs font-medium text-danger mb-1 uppercase tracking-wider">
                            {fieldTitle('stderr')}
                        </h4>
                        <div class="relative">
                            <div class="p-3 rounded-lg bg-danger-soft border border-danger/30">
                                <pre
                                    class="text-xs text-danger whitespace-pre-wrap break-words font-mono bg-transparent p-0 pr-8">{@render ansi(
                                        result.stderr,
                                    )}</pre>
                            </div>
                            <div class="absolute bottom-2 right-2 group">
                                <button
                                    type="button"
                                    class="inline-flex items-center p-1.5 rounded-lg text-danger hover:text-danger hover:bg-danger-soft transition-colors duration-150 cursor-pointer opacity-70 hover:opacity-100"
                                    aria-label="Copy error text to clipboard"
                                    onclick={() => copyToClipboard(result!.stderr!, 'Error text')}
                                >
                                    <Copy class="w-4 h-4" />
                                </button>
                                <div
                                    class="absolute bottom-8 right-0 z-10 px-2 py-1 text-xs bg-tooltip text-white rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none whitespace-nowrap"
                                >
                                    Copy errors
                                </div>
                            </div>
                        </div>
                    </div>
                {/if}

                {#if result.resource_usage}
                    {@const usage = result.resource_usage}
                    <div class="p-3 rounded-lg bg-info-soft border border-info/30 text-xs space-y-1">
                        <h4 class="text-xs font-medium text-info mb-2 uppercase tracking-wider">
                            {fieldTitle('resource_usage')}
                        </h4>
                        <dl class="grid grid-cols-1 sm:grid-cols-3 gap-x-3 gap-y-1">
                            {@render usageField(
                                'execution_time_wall_seconds',
                                usage.execution_time_wall_seconds.toFixed(3),
                            )}
                            {@render usageField('cpu_time_jiffies', usage.cpu_time_jiffies)}
                            {@render usageField('peak_memory_kb', usage.peak_memory_kb)}
                        </dl>
                    </div>
                {/if}
            </div>
        {:else}
            <div class="flex items-center justify-center h-full text-center text-fg-muted italic p-4">
                Write some code and click "Run Script" to see the output.
            </div>
        {/if}
    </div>
</div>
