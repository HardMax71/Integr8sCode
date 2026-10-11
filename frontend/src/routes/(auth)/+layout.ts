import { requireAuth } from '#lib/auth-guard.ts';
import type { LayoutLoad } from './$types';

export const load: LayoutLoad = async ({ url }) => {
    await requireAuth(url);
};
