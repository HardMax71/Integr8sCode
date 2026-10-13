import { redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';
import { toast } from 'svelte-sonner';
import { UserRole } from '#lib/api/index.ts';
import type { LayoutLoad } from './$types';

// Runs before the page mounts, so a non-admin never fires an admin API call
export const load: LayoutLoad = async ({ parent, url }) => {
    const { user } = await parent();
    if (!user) redirect(307, `${resolve('/login')}?${new URLSearchParams({ redirect: url.pathname + url.search })}`);
    if (user.role !== UserRole.ADMIN) {
        toast.error('Admin access required');
        redirect(307, resolve('/'));
    }
    return { user };
};
