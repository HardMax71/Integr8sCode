<script lang="ts">
    import { FilePlus, Upload, Download, Save } from '@lucide/svelte';

    interface Props {
        authenticated: boolean;
        onnew: () => void;
        onupload: () => void;
        onsave: () => void;
        onexport: () => void;
    }

    let { authenticated, onnew, onupload, onsave, onexport }: Props = $props();
</script>

<div class="space-y-3">
    <h4 class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">File Actions</h4>
    <div class="grid grid-cols-2 gap-2">
        <button type="button" class="btn btn-secondary-outline btn-sm inline-flex items-center justify-center space-x-1"
                onclick={onnew} title="Start a new script">
            <FilePlus class="w-4 h-4" /><span>New</span>
        </button>
        <button type="button" class="btn btn-secondary-outline btn-sm inline-flex items-center justify-center space-x-1"
                onclick={onupload} title="Upload a file">
            <Upload class="w-4 h-4" /><span>Upload</span>
        </button>
        {#if authenticated}
            <button type="button" class="btn btn-primary btn-sm inline-flex items-center justify-center space-x-1"
                    onclick={onsave} title="Save current script">
                <Save class="w-4 h-4" /><span>Save</span>
            </button>
        {/if}
        <button type="button" class="btn btn-secondary-outline btn-sm inline-flex items-center justify-center space-x-1"
                onclick={onexport} title="Download current script">
            <Download class="w-4 h-4" /><span>Export</span>
        </button>
    </div>
</div>
