import { redirect } from '@sveltejs/kit';
import { toast } from 'svelte-sonner';
import { UserRole } from '#lib/api/index.ts';
import { authStore } from '#stores/auth.svelte.ts';

/**
 * Send a signed-out visitor to /login, remembering where they were going.
 * @param url - The URL being loaded
 */
export async function requireAuth(url: URL): Promise<void> {
    const signedIn = await authStore.waitForInit().catch(() => false);
    if (signedIn && authStore.isAuthenticated) return;
    sessionStorage.setItem('redirectAfterLogin', url.pathname + url.search);
    redirect(307, '/login');
}

/**
 * Like requireAuth, and also send a signed-in non-admin home, before the page fires any admin API call.
 * @param url - The URL being loaded
 */
export async function requireAdmin(url: URL): Promise<void> {
    await requireAuth(url);
    if (authStore.userRole === UserRole.ADMIN) return;
    toast.error('Admin access required');
    redirect(307, '/');
}
