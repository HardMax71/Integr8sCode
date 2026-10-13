<script lang="ts">
    import { resolve } from '$app/paths';
    import { goto } from '$app/navigation';
    import { createMutation, useQueryClient } from '@tanstack/svelte-query';
    import {
        getUserSettingsApiV1UserSettingsGetQueryKey,
        logoutApiV1AuthLogoutPostMutation,
        Theme,
        updateThemeApiV1UserSettingsThemePutMutation,
        UserRole,
    } from '#lib/api/index.ts';
    import { authStore } from '#stores/auth.svelte.ts';
    import { themeStore, toggleTheme } from '#stores/theme.svelte.ts';
    import { fade } from 'svelte/transition';
    import { MediaQuery } from 'svelte/reactivity';
    import NotificationCenter from '#components/NotificationCenter.svelte';
    import { DropdownMenu } from 'bits-ui';
    import {
        Sun,
        Moon,
        MonitorCog,
        Menu,
        X,
        LogIn,
        UserPlus,
        LogOut,
        User,
        ChevronDown,
        Settings,
    } from '@lucide/svelte';

    const desktop = new MediaQuery('min-width: 1024px');
    let menuRequested = $state(false);
    const isMenuActive = $derived(menuRequested && !desktop.current);

    function toggleMenu() {
        menuRequested = !isMenuActive;
    }

    function closeMenu() {
        menuRequested = false;
    }

    const queryClient = useQueryClient();

    const logout = createMutation(() => ({
        ...logoutApiV1AuthLogoutPostMutation(),
        onSettled: () => {
            authStore.clearAuth();
            closeMenu();
            void goto(resolve('/login'));
        },
    }));

    const saveTheme = createMutation(() => ({
        ...updateThemeApiV1UserSettingsThemePutMutation(),
        onSuccess: (data) => {
            queryClient.setQueryData(getUserSettingsApiV1UserSettingsGetQueryKey(), data);
        },
    }));

    function handleToggleTheme() {
        toggleTheme();
        if (authStore.isAuthenticated) saveTheme.mutate({ body: { theme: themeStore.value } });
    }

    function handleLogout() {
        logout.mutate({});
    }
</script>

<header
    class="fixed top-0 left-0 right-0 bg-bg-alt/80 dark:bg-dark-bg-alt/80 backdrop-blur-md border-b border-border-default dark:border-dark-border-default shadow-xs z-50 transition-colors duration-300 h-16"
>
    <div class="app-container h-full">
        <nav class="flex items-center justify-between h-full">
            <div class="flex items-center shrink-0">
                <a href={resolve('/')} onclick={closeMenu} class="flex items-center space-x-2 group">
                    <img
                        src="/favicon.png"
                        alt="Integr8sCode Logo"
                        class="h-8 max-h-8 w-auto transition-all duration-200 group-hover:scale-110"
                    />
                    <span
                        class="font-semibold text-xl tracking-tight text-fg-default dark:text-dark-fg-default group-hover:text-primary dark:group-hover:text-primary-light transition-colors duration-200"
                    >
                        Integr8sCode
                    </span>
                </a>
            </div>

            <div class="hidden lg:flex items-center space-x-6 flex-grow justify-center">
                <div></div>
            </div>

            <div class="flex items-center space-x-3">
                <button
                    type="button"
                    onclick={handleToggleTheme}
                    title="Toggle theme"
                    aria-label="Toggle theme"
                    class="btn btn-ghost btn-icon text-fg-muted dark:text-dark-fg-muted hover:text-fg-default dark:hover:text-dark-fg-default"
                >
                    {#if themeStore.value === Theme.LIGHT}
                        <Sun class="w-5 h-5" />
                    {:else if themeStore.value === Theme.DARK}
                        <Moon class="w-5 h-5" />
                    {:else}
                        <MonitorCog class="w-5 h-5" />
                    {/if}
                </button>

                <div class="hidden lg:flex items-center space-x-3">
                    {#if authStore.isAuthenticated}
                        <NotificationCenter />
                        <DropdownMenu.Root>
                            <DropdownMenu.Trigger
                                aria-label="User menu"
                                class="flex items-center space-x-2 btn btn-ghost btn-sm group"
                            >
                                <User class="w-5 h-5" />
                                <span class="hidden xl:inline font-medium">{authStore.user?.username}</span>
                                <ChevronDown
                                    class="w-4 h-4 transition-transform duration-200 group-data-[state=open]:rotate-180"
                                />
                            </DropdownMenu.Trigger>
                            <DropdownMenu.Portal>
                                <DropdownMenu.Content align="end" sideOffset={8} class="floating-panel w-64">
                                    <div class="flex items-center gap-3 px-2 py-1.5">
                                        <span
                                            class="w-7 h-7 rounded-full bg-primary/20 dark:bg-primary/30 flex items-center justify-center shrink-0 text-xs font-semibold text-primary dark:text-primary-light"
                                        >
                                            {authStore.user?.username.charAt(0).toUpperCase() ?? '?'}
                                        </span>
                                        <span class="min-w-0">
                                            <span class="block text-sm font-medium truncate">
                                                {authStore.user?.username}
                                                {#if authStore.user?.role === UserRole.ADMIN}
                                                    <span
                                                        class="text-xs text-primary dark:text-primary-light font-medium ml-1"
                                                        >{authStore.user?.role}</span
                                                    >
                                                {/if}
                                            </span>
                                            <span class="block text-xs text-fg-muted dark:text-dark-fg-muted truncate"
                                                >{authStore.user?.email}</span
                                            >
                                        </span>
                                    </div>
                                    <DropdownMenu.Separator
                                        class="my-1 h-px bg-border-default dark:bg-dark-border-default"
                                    />
                                    {#if authStore.user?.role === UserRole.ADMIN}
                                        <DropdownMenu.Item class="floating-item">
                                            {#snippet child({ props })}
                                                <a href={resolve('/admin/events')} {...props}
                                                    ><Settings class="w-4 h-4" />Admin</a
                                                >
                                            {/snippet}
                                        </DropdownMenu.Item>
                                    {/if}
                                    <DropdownMenu.Item class="floating-item">
                                        {#snippet child({ props })}
                                            <a href={resolve('/(auth)/settings')} {...props}
                                                ><User class="w-4 h-4" />Settings</a
                                            >
                                        {/snippet}
                                    </DropdownMenu.Item>
                                    <DropdownMenu.Separator
                                        class="my-1 h-px bg-border-default dark:bg-dark-border-default"
                                    />
                                    <DropdownMenu.Item
                                        class="floating-item text-red-600 dark:text-red-400"
                                        onSelect={handleLogout}
                                    >
                                        <LogOut class="w-4 h-4" />Logout
                                    </DropdownMenu.Item>
                                </DropdownMenu.Content>
                            </DropdownMenu.Portal>
                        </DropdownMenu.Root>
                    {:else}
                        <a href={resolve('/login')} onclick={closeMenu} class="btn btn-secondary-outline btn-sm">
                            Login
                        </a>
                        <a
                            href={resolve('/register')}
                            onclick={closeMenu}
                            class="btn btn-primary btn-sm hover:text-white"
                        >
                            Register
                        </a>
                    {/if}
                </div>

                <div data-testid="mobile-menu-toggle" class="block lg:hidden">
                    <button
                        type="button"
                        onclick={toggleMenu}
                        aria-label={isMenuActive ? 'Close menu' : 'Open menu'}
                        class="btn btn-ghost btn-icon text-fg-muted dark:text-dark-fg-muted hover:text-fg-default dark:hover:text-dark-fg-default"
                    >
                        {#if isMenuActive}
                            <X class="h-5 w-5" />
                        {:else}
                            <Menu class="h-5 w-5" />
                        {/if}
                    </button>
                </div>
            </div>
        </nav>
    </div>

    {#if isMenuActive}
        <div
            data-testid="mobile-menu"
            class="lg:hidden absolute top-16 left-0 right-0 bg-bg-alt dark:bg-dark-bg-alt shadow-lg border-t border-border-default dark:border-dark-border-default"
            in:fade={{ duration: 150 }}
            out:fade={{ duration: 100 }}
        >
            <div class="px-2 pt-2 pb-3 space-y-1 sm:px-3">
                <div class="pt-3 mt-2 border-t border-border-default dark:border-dark-border-default">
                    {#if authStore.isAuthenticated}
                        <div class="px-3 py-2">
                            <div class="text-sm font-medium text-fg-default dark:text-dark-fg-default">
                                {authStore.user?.username}
                            </div>
                            <div class="text-xs text-fg-muted dark:text-dark-fg-muted">{authStore.user?.role}</div>
                        </div>
                        {#if authStore.user?.role === UserRole.ADMIN}
                            <a
                                href={resolve('/admin/events')}
                                onclick={closeMenu}
                                class="block px-3 py-2 rounded-md text-base font-medium text-fg-default dark:text-dark-fg-default hover:bg-neutral-100 dark:hover:bg-neutral-700 flex items-center"
                            >
                                <Settings class="w-5 h-5 mr-2 -ml-1" /> Admin Panel
                            </a>
                        {/if}
                        <a
                            href={resolve('/(auth)/settings')}
                            onclick={closeMenu}
                            class="block px-3 py-2 rounded-md text-base font-medium text-fg-default dark:text-dark-fg-default hover:bg-neutral-100 dark:hover:bg-neutral-700"
                        >
                            Settings
                        </a>
                        <button
                            type="button"
                            onclick={handleLogout}
                            class="w-full text-left block px-3 py-2 rounded-md text-base font-medium text-red-700 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30 hover:text-red-800 dark:hover:text-red-300 flex items-center"
                        >
                            <LogOut class="w-5 h-5 mr-2 -ml-1" /> Logout
                        </button>
                    {:else}
                        <a
                            href={resolve('/login')}
                            onclick={closeMenu}
                            class="block px-3 py-2 rounded-md text-base font-medium text-fg-default dark:text-dark-fg-default hover:bg-neutral-100 dark:hover:bg-neutral-700 flex items-center"
                        >
                            <LogIn class="w-5 h-5 mr-2 -ml-1" /> Login
                        </a>
                        <a
                            href={resolve('/register')}
                            onclick={closeMenu}
                            class="block px-3 py-2 rounded-md text-base font-medium text-fg-default dark:text-dark-fg-default hover:bg-neutral-100 dark:hover:bg-neutral-700 flex items-center"
                        >
                            <UserPlus class="w-5 h-5 mr-2 -ml-1" /> Register
                        </a>
                    {/if}
                </div>
            </div>
        </div>
    {/if}
</header>
