<script lang="ts">
    import { Lightbulb } from '@lucide/svelte';
    import { fieldTitle } from '#lib/formatters.ts';
    import { draft } from '#lib/editor/index.ts';
    import LoadExample from '#components/editor/LoadExample.svelte';
</script>

<div class="editor-toolbar flex items-center justify-between px-3 py-1 bg-page border-b border-border shrink-0">
    <div>
        <label for="scriptNameInput" class="sr-only">{fieldTitle('name')}</label>
        <input
            id="scriptNameInput"
            type="text"
            class="form-input-bare"
            placeholder="Unnamed Script"
            bind:value={draft.current.name}
        />
    </div>
    <div class="flex items-center space-x-2">
        <LoadExample class="btn btn-secondary-outline btn-sm inline-flex items-center space-x-1.5">
            <Lightbulb class="w-4 h-4" />
            <span class="hidden sm:inline">Example</span>
        </LoadExample>
    </div>
</div>
