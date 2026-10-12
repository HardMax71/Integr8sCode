import { PersistedState } from 'runed';
import * as z from 'zod/mini';
import { zExecutionRequest, type SavedScriptResponse } from '#lib/api/index.ts';

/** The script open in the editor, under the names the API gives a saved script */
export type Draft = Pick<SavedScriptResponse, 'name' | 'script' | 'lang' | 'lang_version'> & {
    script_id: string | null;
};

// Not synced across tabs, so two tabs can edit two scripts
export const draft = new PersistedState<Draft>(
    'editorDraft',
    {
        script_id: null,
        name: '',
        script: '',
        ...z.pick(zExecutionRequest, { lang: true, lang_version: true }).parse({}),
    },
    { syncTabs: false },
);

export function openScript({ script_id, name, script, lang, lang_version }: SavedScriptResponse): void {
    draft.current = { script_id, name, script, lang, lang_version };
}

export function newScript(): void {
    draft.current = { ...draft.current, script_id: null, name: '', script: '' };
}
