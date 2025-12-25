<script lang="ts">
    import { Lightbulb } from '@lucide/svelte';

    interface Props {
        name: string;
        onexample: () => void;
        onchange: (name: string) => void;
    }

    let { name, onexample, onchange }: Props = $props();
</script>

<div class="editor-toolbar flex items-center justify-between px-3 py-1 bg-bg-default dark:bg-dark-bg-default border-b border-border-default dark:border-dark-border-default shrink-0">
    <div>
        <label for="scriptNameInput" class="sr-only">Script Name</label>
        <input id="scriptNameInput" type="text" class="form-input-bare"
               placeholder="Unnamed Script" value={name} oninput={(e) => onchange(e.currentTarget.value)} />
    </div>
    <div class="flex items-center space-x-2">
        <button class="btn btn-secondary-outline btn-sm inline-flex items-center space-x-1.5"
                onclick={onexample} title="Load an example script for the selected language">
            <Lightbulb class="w-4 h-4" />
            <span class="hidden sm:inline">Example</span>
        </button>
    </div>
</div>
