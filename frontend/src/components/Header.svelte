<script lang="ts">
  import { route, goto } from "@mateothegreat/svelte5-router";
  import { authStore } from "$stores/auth.svelte";
  import { themeStore, toggleTheme } from "$stores/theme.svelte";
  import { fade } from 'svelte/transition';
  import { onMount, onDestroy } from 'svelte';
  import NotificationCenter from '$components/NotificationCenter.svelte';
  import { Sun, Moon, MonitorCog, Menu, X, LogIn, UserPlus, LogOut, User, ChevronDown, Settings } from '@lucide/svelte';

  let isMenuActive = $state(false);
  let isMobile = $state(false);
  let resizeListener: (() => void) | null = null;
  let showUserDropdown = $state(false);
  let logoImgClass = "h-8 max-h-8 w-auto transition-all duration-200 group-hover:scale-110";


  function toggleMenu() {
    isMenuActive = !isMenuActive;
  }

  function closeMenu() {
    isMenuActive = false;
    showUserDropdown = false;
  }

  async function handleLogout() {
    await authStore.logout();
    closeMenu();
    goto('/login');
  }

  function handleClickOutside(event: MouseEvent) {
    if (showUserDropdown && !(event.target as Element)?.closest('.user-dropdown-container')) {
      showUserDropdown = false;
    }
  }

  // Consolidated onMount - handles both resize and click outside listeners
  onMount(() => {
    if (typeof window === 'undefined') return;

    // Mobile detection and resize handling
    const checkMobile = () => {
      isMobile = window.innerWidth < 1024;
      if (!isMobile && isMenuActive) {
        isMenuActive = false;
      }
    };
    checkMobile();
    resizeListener = checkMobile;
    window.addEventListener('resize', resizeListener);

    // Click outside handling for dropdown
    document.addEventListener('click', handleClickOutside);
  });

  onDestroy(() => {
    if (typeof window === 'undefined') return;
    if (resizeListener) {
      window.removeEventListener('resize', resizeListener);
    }
    document.removeEventListener('click', handleClickOutside);
  });

  const getLinkClasses = (isActive: boolean, isMobileLink = false) => {
    const baseDesktop = "text-sm font-medium transition-colors duration-200";
    const baseMobile = "block text-base font-medium transition-colors duration-200 px-3 py-2 rounded-md hover:bg-neutral-100 dark:hover:bg-neutral-700";
    const active = "text-primary dark:text-primary-light bg-primary/10 dark:bg-primary/20";
    const inactiveDesktop = "text-fg-muted dark:text-dark-fg-muted hover:text-fg-default dark:hover:text-dark-fg-default";
    const inactiveMobile = "text-fg-default dark:text-dark-fg-default";

    const base = isMobileLink ? baseMobile : baseDesktop;
    const inactive = isMobileLink ? inactiveMobile : inactiveDesktop;

    return `${base} ${isActive ? active : inactive}`;
  };

</script>

<header class="fixed top-0 left-0 right-0 bg-bg-alt/80 dark:bg-dark-bg-alt/80 backdrop-blur-md border-b border-border-default dark:border-dark-border-default shadow-xs z-50 transition-colors duration-300 h-16">
  <div class="app-container h-full">
    <nav class="flex items-center justify-between h-full">
      <div class="flex items-center shrink-0">
        <a href="/" use:route onclick={closeMenu} class="flex items-center space-x-2 group">
          <img src="/favicon.png" alt="Integr8sCode Logo" class={logoImgClass} />
          <span class="font-semibold text-xl tracking-tight text-fg-default dark:text-dark-fg-default group-hover:text-primary dark:group-hover:text-primary-light transition-colors duration-200">
            Integr8sCode
          </span>
        </a>
      </div>

      <div class="hidden lg:flex items-center space-x-6 flex-grow justify-center">
         <div></div>
      </div>

      <div class="flex items-center space-x-3">
        <button type="button" onclick={toggleTheme} title="Toggle theme" aria-label="Toggle theme" class="btn btn-ghost btn-icon text-fg-muted dark:text-dark-fg-muted hover:text-fg-default dark:hover:text-dark-fg-default">
          {#if themeStore.value === 'light'}
            <Sun class="w-5 h-5" />
          {:else if themeStore.value === 'dark'}
            <Moon class="w-5 h-5" />
          {:else}
            <MonitorCog class="w-5 h-5" />
          {/if}
        </button>

        <div class="hidden lg:flex items-center space-x-3">
          {#if authStore.isAuthenticated}
            <NotificationCenter />
            <!-- User dropdown for all authenticated users -->
            <div class="relative user-dropdown-container">
              <button type="button"
                onclick={(e) => { e.stopPropagation(); showUserDropdown = !showUserDropdown; }}
                class="flex items-center space-x-2 btn btn-ghost btn-sm"
              >
                <div class="flex items-center space-x-2">
                  <User class="w-5 h-5" />
                  <span class="hidden xl:inline font-medium">{authStore.username}</span>
                  <span class="transition-transform duration-200" class:rotate-180={showUserDropdown}>
                    <ChevronDown class="w-4 h-4" />
                  </span>
                </div>
              </button>
              
              {#if showUserDropdown}
                <div class="absolute right-0 mt-2 w-[min(92vw,360px)] min-w-[260px] bg-bg-default dark:bg-dark-bg-default rounded-md shadow-lg ring-1 ring-black/5 dark:ring-white/10 z-50"
                     in:fade={{ duration: 150 }}
                     out:fade={{ duration: 100 }}>
                  <div class="p-3">
                    <div class="flex items-center gap-3">
                      <div class="w-7 h-7 rounded-full bg-primary/20 dark:bg-primary/30 flex items-center justify-center shrink-0">
                        <span class="text-xs font-semibold text-primary dark:text-primary-light">
                          {authStore.username?.charAt(0).toUpperCase() ?? '?'}
                        </span>
                      </div>
                      <div class="min-w-0">
                        <p class="text-sm font-medium text-fg-default dark:text-dark-fg-default truncate">
                          {authStore.username}
                          {#if authStore.userRole === 'admin'}
                            <span class="text-xs text-primary dark:text-primary-light font-medium ml-1">(Admin)</span>
                          {/if}
                        </p>
                        <p class="text-xs text-fg-muted dark:text-dark-fg-muted truncate">
                          {authStore.userEmail || 'No email set'}
                        </p>
                      </div>
                      <div class="mx-1 sm:mx-2 h-6 w-px bg-border-default dark:bg-dark-border-default"></div>
                    </div>
                    <div class="mt-3 flex flex-col sm:flex-row gap-2">
                      {#if authStore.userRole === 'admin'}
                        <button type="button"
                          onclick={() => {
                            showUserDropdown = false;
                            goto('/admin/events');
                          }}
                          class="btn btn-secondary-outline btn-sm flex-1"
                        >
                          Admin
                        </button>
                      {/if}
                      <a
                        href="/settings"
                        use:route
                        onclick={() => showUserDropdown = false}
                        class="btn btn-secondary-outline btn-sm flex-1 text-center"
                      >
                        Settings
                      </a>
                      <button type="button"
                        onclick={handleLogout}
                        class="btn btn-danger-outline btn-sm flex-1"
                      >
                        Logout
                      </button>
                    </div>
                  </div>
                </div>
              {/if}
            </div>
          {:else}
            <a href="/login" use:route onclick={closeMenu} class="btn btn-secondary-outline btn-sm">
              Login
            </a>
            <a href="/register" use:route onclick={closeMenu} class="btn btn-primary btn-sm hover:text-white">
              Register
            </a>
          {/if}
        </div>

        <div class="block lg:hidden">
          <button type="button" onclick={toggleMenu} aria-label={isMenuActive ? 'Close menu' : 'Open menu'} class="btn btn-ghost btn-icon text-fg-muted dark:text-dark-fg-muted hover:text-fg-default dark:hover:text-dark-fg-default">
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
    <div class="lg:hidden absolute top-16 left-0 right-0 bg-bg-alt dark:bg-dark-bg-alt shadow-lg border-t border-border-default dark:border-dark-border-default"
         in:fade={{ duration: 150 }} out:fade={{ duration: 100 }}>
      <div class="px-2 pt-2 pb-3 space-y-1 sm:px-3">

        <div class="pt-3 mt-2 border-t border-border-default dark:border-dark-border-default">
          {#if authStore.isAuthenticated}
            <div class="px-3 py-2">
               <div class="text-sm font-medium text-fg-default dark:text-dark-fg-default">{authStore.username}</div>
               <div class="text-xs text-fg-muted dark:text-dark-fg-muted">
                 {#if authStore.userRole === 'admin'}
                   Administrator
                 {:else}
                   Logged in
                 {/if}
               </div>
            </div>
            {#if authStore.userRole === 'admin'}
              <a href="/admin/events" use:route onclick={closeMenu} class="block px-3 py-2 rounded-md text-base font-medium text-fg-default dark:text-dark-fg-default hover:bg-neutral-100 dark:hover:bg-neutral-700 flex items-center">
                <Settings class="w-5 h-5 mr-2 -ml-1" /> Admin Panel
              </a>
            {/if}
            <a href="/settings" use:route onclick={closeMenu} class="block px-3 py-2 rounded-md text-base font-medium text-fg-default dark:text-dark-fg-default hover:bg-neutral-100 dark:hover:bg-neutral-700">
              Settings
            </a>
            <button type="button" onclick={handleLogout} class="w-full text-left block px-3 py-2 rounded-md text-base font-medium text-red-700 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30 hover:text-red-800 dark:hover:text-red-300 flex items-center">
              <LogOut class="w-5 h-5 mr-2 -ml-1" /> Logout
            </button>
          {:else}
            <a href="/login" use:route onclick={closeMenu} class="block px-3 py-2 rounded-md text-base font-medium text-fg-default dark:text-dark-fg-default hover:bg-neutral-100 dark:hover:bg-neutral-700 flex items-center">
              <LogIn class="w-5 h-5 mr-2 -ml-1" /> Login
            </a>
            <a href="/register" use:route onclick={closeMenu} class="block px-3 py-2 rounded-md text-base font-medium text-fg-default dark:text-dark-fg-default hover:bg-neutral-100 dark:hover:bg-neutral-700 flex items-center">
              <UserPlus class="w-5 h-5 mr-2 -ml-1" /> Register
            </a>
          {/if}
        </div>
      </div>
    </div>
  {/if}
</header>
