import { python } from '@codemirror/lang-python';
import { javascript } from '@codemirror/lang-javascript';
import { go } from '@codemirror/lang-go';
import { StreamLanguage, type LanguageSupport } from '@codemirror/language';
import { ruby } from '@codemirror/legacy-modes/mode/ruby';
import { shell } from '@codemirror/legacy-modes/mode/shell';
import type { Extension } from '@codemirror/state';

const languageExtensions: Record<string, () => LanguageSupport | Extension> = {
    python: () => python(),
    node: () => javascript(),
    go: () => go(),
    ruby: () => StreamLanguage.define(ruby),
    bash: () => StreamLanguage.define(shell),
};

export function getLanguageExtension(lang: string): LanguageSupport | Extension {
    return languageExtensions[lang]?.() ?? python();
}
