import { getCurrentUserProfileApiV1AuthMeGet } from '#lib/api/index.ts';
import type { LayoutLoad } from './$types';

// A client-rendered SPA: adapter-static serves every route through the 200.html fallback
export const ssr = false;

// Without throwOnError a 401 comes back as data: nobody is signed in, which is no error for the query client to show
export const load: LayoutLoad = async () => {
    const { data } = await getCurrentUserProfileApiV1AuthMeGet();
    return { user: data ?? null };
};
