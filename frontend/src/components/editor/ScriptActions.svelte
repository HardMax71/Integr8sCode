<script lang="ts">
    import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
    import { FilePlus, Upload, Download, Save } from '@lucide/svelte';
    import * as z from 'zod/mini';
    import { toast } from 'svelte-sonner';
    import {
        createSavedScriptApiV1ScriptsPostMutation,
        getK8sResourceLimitsApiV1K8sLimitsGetOptions,
        listSavedScriptsApiV1ScriptsGetQueryKey,
        updateSavedScriptApiV1ScriptsScriptIdPutMutation,
        zExecutionRequest,
    } from '#lib/api/index.ts';
    import { firstIssue } from '#lib/validation.ts';
    import { draft, executionContext, newScript, pickRuntime } from '#lib/editor/index.ts';

    const queryClient = useQueryClient();
    const execution = executionContext.get();
    const limits = createQuery(() => getK8sResourceLimitsApiV1K8sLimitsGetOptions());
    const runtimes = $derived(limits.data?.supported_runtimes ?? {});
    const runtime = $derived(pickRuntime(draft.current, runtimes));
    const extensions = $derived(Object.values(runtimes).map((info) => `.${info.file_ext}`));
    let fileInput: HTMLInputElement;

    const refreshScripts = () => queryClient.invalidateQueries({ queryKey: listSavedScriptsApiV1ScriptsGetQueryKey() });

    const create = createMutation(() => ({
        ...createSavedScriptApiV1ScriptsPostMutation(),
        onSuccess: (saved) => {
            draft.current.script_id = saved.script_id;
            toast.success('Script saved successfully.');
            return refreshScripts();
        },
    }));

    const update = createMutation(() => ({
        ...updateSavedScriptApiV1ScriptsScriptIdPutMutation(),
        onSuccess: () => {
            toast.success('Script updated successfully.');
            return refreshScripts();
        },
    }));

    function startNew(): void {
        newScript();
        execution.reset();
        toast.info('New script started.');
    }

    function save(): void {
        const { script_id, ...script } = draft.current;
        const body = { ...script, ...runtime };
        if (!body.name.trim()) {
            toast.warning('Please provide a name for your script.');
            return;
        }
        if (!script_id) {
            create.mutate({ body });
            return;
        }
        update.mutate(
            { path: { script_id }, body },
            {
                // Deleted elsewhere, so save it as a new script
                onError: (err) => {
                    if (err.status === 404) create.mutate({ body });
                },
            },
        );
    }

    async function upload(event: Event & { currentTarget: HTMLInputElement }): Promise<void> {
        const file = event.currentTarget.files?.[0];
        event.currentTarget.value = '';
        if (!file) return;

        const ext = file.name.split('.').pop()?.toLowerCase();
        const lang = Object.keys(runtimes).find((l) => runtimes[l]?.file_ext === ext);
        if (!lang) {
            toast.error(`Unsupported file type. Allowed: ${extensions.join(', ')}`);
            return;
        }
        const text = await file.text().catch(() => null);
        if (text === null) {
            toast.error('Failed to read the selected file.');
            return;
        }
        const parsed = z.pick(zExecutionRequest, { script: true }).safeParse({ script: text });
        if (!parsed.success) {
            toast.error(firstIssue(parsed.error));
            return;
        }
        draft.current = {
            script_id: null,
            name: file.name,
            script: parsed.data.script,
            lang,
            lang_version: runtimes[lang]?.versions[0] ?? '',
        };
        execution.reset();
        toast.info(`Loaded ${lang} script from ${file.name}`);
    }

    function download(): void {
        const ext = runtimes[runtime.lang]?.file_ext ?? 'txt';
        const base = draft.current.name.trim().replace(/\.[^.]+$/, '') || 'script';
        const link = document.createElement('a');
        link.href = URL.createObjectURL(new Blob([draft.current.script], { type: 'text/plain;charset=utf-8' }));
        link.download = `${base}.${ext}`;
        link.click();
        URL.revokeObjectURL(link.href);
    }
</script>

<input type="file" accept={extensions.join(',')} bind:this={fileInput} class="hidden" onchange={upload} />

<div class="space-y-3">
    <h4 class="text-xs font-medium text-fg-muted uppercase tracking-wider">File Actions</h4>
    <div class="grid grid-cols-2 gap-2">
        <button
            type="button"
            class="btn btn-secondary-outline btn-sm inline-flex items-center justify-center space-x-1"
            onclick={startNew}
            title="Start a new script"
        >
            <FilePlus class="w-4 h-4" /><span>New</span>
        </button>
        <button
            type="button"
            class="btn btn-secondary-outline btn-sm inline-flex items-center justify-center space-x-1"
            onclick={() => fileInput.click()}
            title="Upload a file"
        >
            <Upload class="w-4 h-4" /><span>Upload</span>
        </button>
        <button
            type="button"
            class="btn btn-primary btn-sm inline-flex items-center justify-center space-x-1"
            onclick={save}
            title="Save current script"
        >
            <Save class="w-4 h-4" /><span>Save</span>
        </button>
        <button
            type="button"
            class="btn btn-secondary-outline btn-sm inline-flex items-center justify-center space-x-1"
            onclick={download}
            title="Download current script"
        >
            <Download class="w-4 h-4" /><span>Export</span>
        </button>
    </div>
</div>
