<script lang="ts">
    import { resolve } from '$app/paths';
    import { goto } from '$app/navigation';
    import { page } from '$app/state';
    import { createMutation, useQueryClient } from '@tanstack/svelte-query';
    import {
        getUserSettingsApiV1UserSettingsGetQueryKey,
        logoutApiV1AuthLogoutPostMutation,
        Theme,
        updateThemeApiV1UserSettingsThemePutMutation,
        UserRole,
    } from '#lib/api/index.ts';
    import { setMode, userPrefersMode } from 'mode-watcher';
    import { prefersReducedMotion } from 'svelte/motion';
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
            // Nothing the previous user loaded may show to the next one
            queryClient.clear();
            closeMenu();
            void goto(resolve('/login'), { refreshAll: true });
        },
    }));

    const saveTheme = createMutation(() => ({
        ...updateThemeApiV1UserSettingsThemePutMutation(),
        onSuccess: (data) => {
            queryClient.setQueryData(getUserSettingsApiV1UserSettingsGetQueryKey(), data);
        },
    }));

    function handleToggleTheme() {
        const themes = Object.values(Theme);
        const next = themes[(themes.indexOf(userPrefersMode.current) + 1) % themes.length]!;
        setMode(next);
        if (page.data.user) saveTheme.mutate({ body: { theme: next } });
    }

    function handleLogout() {
        logout.mutate({});
    }
</script>

<header class="fixed top-0 left-0 right-0 bg-surface/80 backdrop-blur-md border-b shadow-xs z-50 h-16">
    <div class="app-container h-full">
        <nav class="flex items-center justify-between h-full">
            <a href={resolve('/')} onclick={closeMenu} class="group flex shrink-0 items-center gap-2">
                <img
                    src="/favicon.png"
                    alt="Integr8sCode Logo"
                    class="h-8 w-auto transition-transform group-hover:scale-110"
                />
                <span class="font-semibold text-xl tracking-tight transition-colors group-hover:text-accent">
                    Integr8sCode
                </span>
            </a>

            <div class="flex items-center gap-3">
                <button
                    type="button"
                    onclick={handleToggleTheme}
                    title="Toggle theme"
                    aria-label="Toggle theme"
                    class="btn btn-ghost btn-icon text-fg-muted hover:text-fg"
                >
                    {#if userPrefersMode.current === Theme.LIGHT}
                        <Sun class="size-5" />
                    {:else if userPrefersMode.current === Theme.DARK}
                        <Moon class="size-5" />
                    {:else}
                        <MonitorCog class="size-5" />
                    {/if}
                </button>

                <div class="hidden lg:flex items-center gap-3">
                    {#if page.data.user}
                        {@const user = page.data.user}
                        <NotificationCenter />
                        <DropdownMenu.Root>
                            <DropdownMenu.Trigger aria-label="User menu" class="btn btn-ghost btn-sm group gap-2">
                                <User class="size-5" />
                                <span class="hidden xl:inline font-medium">{user.username}</span>
                                <ChevronDown
                                    class="size-4 transition-transform duration-200 group-data-[state=open]:rotate-180"
                                />
                            </DropdownMenu.Trigger>
                            <DropdownMenu.Portal>
                                <DropdownMenu.Content align="end" sideOffset={8} class="floating-panel w-64">
                                    <div class="flex items-center gap-3 px-2 py-1.5">
                                        <span
                                            class="size-7 rounded-full bg-primary/20 flex items-center justify-center shrink-0 text-xs font-semibold text-accent"
                                        >
                                            {user.username.charAt(0).toUpperCase()}
                                        </span>
                                        <span class="min-w-0">
                                            <span class="block text-sm font-medium truncate">
                                                {user.username}
                                                {#if user.role === UserRole.ADMIN}
                                                    <span class="text-xs text-accent font-medium ml-1">{user.role}</span
                                                    >
                                                {/if}
                                            </span>
                                            <span class="block text-xs text-fg-muted truncate">{user.email}</span>
                                        </span>
                                    </div>
                                    <DropdownMenu.Separator class="my-1 h-px bg-border" />
                                    {#if user.role === UserRole.ADMIN}
                                        <DropdownMenu.Item class="floating-item">
                                            {#snippet child({ props })}
                                                <a href={resolve('/admin/events')} {...props}
                                                    ><Settings class="size-4" />Admin</a
                                                >
                                            {/snippet}
                                        </DropdownMenu.Item>
                                    {/if}
                                    <DropdownMenu.Item class="floating-item">
                                        {#snippet child({ props })}
                                            <a href={resolve('/(auth)/settings')} {...props}
                                                ><User class="size-4" />Settings</a
                                            >
                                        {/snippet}
                                    </DropdownMenu.Item>
                                    <DropdownMenu.Separator class="my-1 h-px bg-border" />
                                    <DropdownMenu.Item class="floating-item text-danger" onSelect={handleLogout}>
                                        <LogOut class="size-4" />Logout
                                    </DropdownMenu.Item>
                                </DropdownMenu.Content>
                            </DropdownMenu.Portal>
                        </DropdownMenu.Root>
                    {:else}
                        <a href={resolve('/login')} onclick={closeMenu} class="btn btn-secondary-outline btn-sm">
                            Login
                        </a>
                        <a href={resolve('/register')} onclick={closeMenu} class="btn btn-primary btn-sm"> Register </a>
                    {/if}
                </div>

                <div data-testid="mobile-menu-toggle" class="lg:hidden">
                    <button
                        type="button"
                        onclick={toggleMenu}
                        aria-label={isMenuActive ? 'Close menu' : 'Open menu'}
                        class="btn btn-ghost btn-icon text-fg-muted hover:text-fg"
                    >
                        {#if isMenuActive}
                            <X class="size-5" />
                        {:else}
                            <Menu class="size-5" />
                        {/if}
                    </button>
                </div>
            </div>
        </nav>
    </div>

    {#if isMenuActive}
        <div
            data-testid="mobile-menu"
            class="lg:hidden absolute top-16 left-0 right-0 bg-surface shadow-lg border-t px-2 py-3 sm:px-3"
            in:fade={{ duration: prefersReducedMotion.current ? 0 : 150 }}
            out:fade={{ duration: prefersReducedMotion.current ? 0 : 100 }}
        >
            {#if page.data.user}
                {@const user = page.data.user}
                <div class="px-3 py-2">
                    <div class="text-sm font-medium">
                        {user.username}
                    </div>
                    <div class="text-xs text-fg-muted">{user.role}</div>
                </div>
                {#if user.role === UserRole.ADMIN}
                    <a href={resolve('/admin/events')} onclick={closeMenu} class="menu-link">
                        <Settings class="size-5" /> Admin Panel
                    </a>
                {/if}
                <a href={resolve('/(auth)/settings')} onclick={closeMenu} class="menu-link"> Settings </a>
                <button type="button" onclick={handleLogout} class="menu-link w-full text-danger hover:bg-danger-soft">
                    <LogOut class="size-5" /> Logout
                </button>
            {:else}
                <a href={resolve('/login')} onclick={closeMenu} class="menu-link">
                    <LogIn class="size-5" /> Login
                </a>
                <a href={resolve('/register')} onclick={closeMenu} class="menu-link">
                    <UserPlus class="size-5" /> Register
                </a>
            {/if}
        </div>
    {/if}
</header>
