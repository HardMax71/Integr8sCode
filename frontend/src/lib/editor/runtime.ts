import type { LanguageInfo } from '#lib/api/index.ts';

export interface Runtime {
    lang: string;
    lang_version: string;
}

/** The draft's runtime while the API offers it, else its language's newest version, else the API's first language */
export function pickRuntime({ lang, lang_version }: Runtime, offered: Record<string, LanguageInfo>): Runtime {
    const versions = offered[lang]?.versions;
    if (versions) return { lang, lang_version: versions.includes(lang_version) ? lang_version : (versions[0] ?? '') };
    const [first] = Object.entries(offered);
    return first ? { lang: first[0], lang_version: first[1].versions[0] ?? '' } : { lang, lang_version };
}
