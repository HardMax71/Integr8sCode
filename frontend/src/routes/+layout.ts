import { error } from '@sveltejs/kit';
import { getCurrentUserProfileApiV1AuthMeGet } from '#lib/api/index.ts';
import type { LayoutLoad } from './$types';

// A client-rendered SPA: adapter-static serves every route through the 200.html fallback
export const ssr = false;

// Without throwOnError a 401 comes back as data: nobody is signed in, which is no error for the query client to show.
// A 429 or a 5xx says nothing about the session, so it shows the error page instead of signing the user out.
export const load: LayoutLoad = async () => {
    const { data, error: failure } = await getCurrentUserProfileApiV1AuthMeGet();
    if (failure && failure.status !== 401 && failure.status !== 0) error(failure.status, failure.detail);
    return { user: data ?? null };
};
