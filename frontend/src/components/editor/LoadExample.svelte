<script lang="ts">
    import type { Snippet } from 'svelte';
    import { createQuery } from '@tanstack/svelte-query';
    import { toast } from 'svelte-sonner';
    import { getExampleScriptsApiV1ExampleScriptsGetOptions } from '#lib/api/index.ts';
    import { draft, executionContext } from '#lib/editor/index.ts';

    interface Props {
        class: string;
        children: Snippet;
    }

    let { class: className, children }: Props = $props();

    const examples = createQuery(() => getExampleScriptsApiV1ExampleScriptsGetOptions());
    const execution = executionContext.get();

    function load(): void {
        const { lang } = draft.current;
        const example = examples.data?.scripts[lang];
        if (!example) {
            toast.warning(`No example script available for ${lang}.`);
            return;
        }
        draft.current.script = example;
        execution.reset();
        toast.info(`Loaded example script for ${lang}.`);
    }
</script>

<button type="button" class={className} onclick={load} title="Load an example script for the selected language">
    {@render children()}
</button>
