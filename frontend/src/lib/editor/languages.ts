import type { Extension } from '@codemirror/state';

const loaders: Record<string, () => Promise<Extension>> = {
    python: async () => (await import('@codemirror/lang-python')).python(),
    node: async () => (await import('@codemirror/lang-javascript')).javascript(),
    go: async () => (await import('@codemirror/lang-go')).go(),
    ruby: async () => {
        const [{ StreamLanguage }, { ruby }] = await Promise.all([
            import('@codemirror/language'),
            import('@codemirror/legacy-modes/mode/ruby'),
        ]);
        return StreamLanguage.define(ruby);
    },
    bash: async () => {
        const [{ StreamLanguage }, { shell }] = await Promise.all([
            import('@codemirror/language'),
            import('@codemirror/legacy-modes/mode/shell'),
        ]);
        return StreamLanguage.define(shell);
    },
};

const plainText = (): Promise<Extension> => Promise.resolve([]);

/** Loads a language's editor mode on first use, so the editor chunk carries none of them */
export function loadLanguage(lang: string): Promise<Extension> {
    return (loaders[lang] ?? plainText)();
}
