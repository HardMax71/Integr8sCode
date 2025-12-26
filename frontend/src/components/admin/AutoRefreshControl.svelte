<script lang="ts">
    import { RefreshCw } from '@lucide/svelte';
    import Spinner from '$components/Spinner.svelte';

    interface RefreshRateOption {
        value: number;
        label: string;
    }

    interface Props {
        enabled: boolean;
        rate: number;
        rateOptions?: RefreshRateOption[];
        loading?: boolean;
        onRefresh: () => void;
        onEnabledChange?: (enabled: boolean) => void;
        onRateChange?: (rate: number) => void;
    }

    let {
        enabled = $bindable(true),
        rate = $bindable(5),
        rateOptions = [
            { value: 5, label: '5 seconds' },
            { value: 10, label: '10 seconds' },
            { value: 30, label: '30 seconds' },
            { value: 60, label: '1 minute' }
        ],
        loading = false,
        onRefresh,
        onEnabledChange,
        onRateChange
    }: Props = $props();

    function handleEnabledChange(e: Event): void {
        const target = e.target as HTMLInputElement;
        enabled = target.checked;
        onEnabledChange?.(enabled);
    }

    function handleRateChange(e: Event): void {
        const target = e.target as HTMLSelectElement;
        rate = parseInt(target.value, 10);
        onRateChange?.(rate);
    }
</script>

<div class="card">
    <div class="p-3 sm:p-4 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4">
        <label class="flex items-center gap-2 cursor-pointer">
            <input
                type="checkbox"
                checked={enabled}
                onchange={handleEnabledChange}
                class="w-4 h-4 rounded border-border-default text-primary focus:ring-primary"
            />
            <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Auto-refresh</span>
        </label>

        {#if enabled}
            <div class="flex items-center gap-2 flex-1 sm:flex-initial">
                <label for="refresh-rate" class="text-xs sm:text-sm text-fg-muted">Every:</label>
                <select
                    id="refresh-rate"
                    value={rate}
                    onchange={handleRateChange}
                    class="form-select-standard"
                >
                    {#each rateOptions as option}
                        <option value={option.value}>{option.label}</option>
                    {/each}
                </select>
            </div>
        {/if}

        <button
            onclick={onRefresh}
            class="sm:ml-auto btn btn-primary btn-sm w-full sm:w-auto"
            disabled={loading}
        >
            {#if loading}
                <Spinner size="small" color="white" className="-ml-1 mr-2" />Refreshing...
            {:else}
                <RefreshCw class="w-4 h-4 mr-1.5" />Refresh Now
            {/if}
        </button>
    </div>
</div>
