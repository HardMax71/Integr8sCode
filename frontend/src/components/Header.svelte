<script>
  import { Link, navigate } from "svelte-routing";
  import { isAuthenticated, username, userRole, logout as authLogout, userEmail } from "../stores/auth";
  import { theme, toggleTheme } from "../stores/theme";
  import { fade } from 'svelte/transition';
  import { onMount, onDestroy } from 'svelte';
  import NotificationCenter from './NotificationCenter.svelte';

  let isMenuActive = false;
  let isMobile;
  let resizeListener;
  let showUserDropdown = false;

  const sunIcon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"></path></svg>`;
  const moonIcon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"></path></svg>`;
  const autoIcon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path></svg>`;
  const menuIcon = `<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"></path></svg>`;
  const closeIcon = `<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>`;
  let logoImgClass = "h-8 max-h-8 w-auto transition-all duration-200 group-hover:scale-110";
  const loginIcon = `<svg class="w-5 h-5 mr-2 -ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1"></path></svg>`;
  const registerIcon = `<svg class="w-5 h-5 mr-2 -ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z"></path></svg>`;
  const logoutIcon = `<svg class="w-5 h-5 mr-2 -ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"></path></svg>`;
  const userIcon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path></svg>`;
  const chevronDownIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>`;
  const adminIcon = `<svg class="w-5 h-5 mr-2 -ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"></path></svg>`;


  onMount(() => {
    const checkMobile = () => {
      if (typeof window !== 'undefined') {
        isMobile = window.innerWidth < 1024;
        if (!isMobile && isMenuActive) {
          isMenuActive = false;
        }
      }
    };
    checkMobile();
    resizeListener = checkMobile;
    if (typeof window !== 'undefined') {
      window.addEventListener('resize', resizeListener);
    }

    return () => {
      if (typeof window !== 'undefined' && resizeListener) {
        window.removeEventListener('resize', resizeListener);
      }
    }
  });

  function toggleMenu() {
    isMenuActive = !isMenuActive;
  }

  function closeMenu() {
    isMenuActive = false;
    showUserDropdown = false;
  }

  async function handleLogout() {
    await authLogout();
    closeMenu();
    navigate('/login');
  }

  function handleClickOutside(event) {
    if (showUserDropdown && !event.target.closest('.user-dropdown-container')) {
      showUserDropdown = false;
    }
  }

  onMount(() => {
    if (typeof window !== 'undefined') {
      document.addEventListener('click', handleClickOutside);
    }
  });

  onDestroy(() => {
    if (typeof window !== 'undefined') {
      document.removeEventListener('click', handleClickOutside);
    }
  });

  const getLinkClasses = (isActive, isMobileLink = false) => {
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
        <Link to="/" on:click={closeMenu} class="flex items-center space-x-2 group">
          <img src="/favicon.png" alt="Integr8sCode Logo" class={logoImgClass} />
          <span class="font-semibold text-xl tracking-tight text-fg-default dark:text-dark-fg-default group-hover:text-primary dark:group-hover:text-primary-light transition-colors duration-200">
            Integr8sCode
          </span>
        </Link>
      </div>

      <div class="hidden lg:flex items-center space-x-6 flex-grow justify-center">
         <div></div>
      </div>

      <div class="flex items-center space-x-3">
        <button on:click={toggleTheme} title="Toggle theme" class="btn btn-ghost btn-icon text-fg-muted dark:text-dark-fg-muted hover:text-fg-default dark:hover:text-dark-fg-default">
          {#if $theme === 'light'}
            {@html sunIcon}
          {:else if $theme === 'dark'}
            {@html moonIcon}
          {:else}
            {@html autoIcon}
          {/if}
        </button>

        <div class="hidden lg:flex items-center space-x-3">
          {#if $isAuthenticated}
            <NotificationCenter />
            <!-- User dropdown for all authenticated users -->
            <div class="relative user-dropdown-container">
              <button 
                on:click={(e) => { e.stopPropagation(); showUserDropdown = !showUserDropdown; }}
                class="flex items-center space-x-2 btn btn-ghost btn-sm"
              >
                <div class="flex items-center space-x-2">
                  {@html userIcon}
                  <span class="hidden xl:inline font-medium">{$username}</span>
                  <span class="transition-transform duration-200" class:rotate-180={showUserDropdown}>
                    {@html chevronDownIcon}
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
                          {$username.charAt(0).toUpperCase()}
                        </span>
                      </div>
                      <div class="min-w-0">
                        <p class="text-sm font-medium text-fg-default dark:text-dark-fg-default truncate">
                          {$username}
                          {#if $userRole === 'admin'}
                            <span class="text-xs text-primary dark:text-primary-light font-medium ml-1">(Admin)</span>
                          {/if}
                        </p>
                        <p class="text-xs text-fg-muted dark:text-dark-fg-muted truncate">
                          {$userEmail || 'No email set'}
                        </p>
                      </div>
                      <div class="mx-1 sm:mx-2 h-6 w-px bg-border-default dark:bg-dark-border-default"></div>
                    </div>
                    <div class="mt-3 flex flex-col sm:flex-row gap-2">
                      {#if $userRole === 'admin'}
                        <button
                          on:click={() => {
                            showUserDropdown = false;
                            navigate('/admin/events');
                          }}
                          class="btn btn-secondary-outline btn-sm flex-1"
                        >
                          Admin
                        </button>
                      {/if}
                      <Link
                        to="/settings"
                        on:click={() => showUserDropdown = false}
                        class="btn btn-secondary-outline btn-sm flex-1 text-center"
                      >
                        Settings
                      </Link>
                      <button
                        on:click={handleLogout}
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
            <Link to="/login" on:click={closeMenu} class="btn btn-secondary-outline btn-sm">
              Login
            </Link>
            <Link to="/register" on:click={closeMenu} class="btn btn-primary btn-sm hover:text-white">
              Register
            </Link>
          {/if}
        </div>

        <div class="block lg:hidden">
          <button on:click={toggleMenu} class="btn btn-ghost btn-icon text-fg-muted dark:text-dark-fg-muted hover:text-fg-default dark:hover:text-dark-fg-default">
            {@html isMenuActive ? closeIcon : menuIcon}
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
          {#if $isAuthenticated}
            <div class="px-3 py-2">
               <div class="text-sm font-medium text-fg-default dark:text-dark-fg-default">{$username}</div>
               <div class="text-xs text-fg-muted dark:text-dark-fg-muted">
                 {#if $userRole === 'admin'}
                   Administrator
                 {:else}
                   Logged in
                 {/if}
               </div>
            </div>
            {#if $userRole === 'admin'}
              <Link to="/admin/events" on:click={closeMenu} class="block px-3 py-2 rounded-md text-base font-medium text-fg-default dark:text-dark-fg-default hover:bg-neutral-100 dark:hover:bg-neutral-700 flex items-center">
                {@html adminIcon} Admin Panel
              </Link>
            {/if}
            <Link to="/settings" on:click={closeMenu} class="block px-3 py-2 rounded-md text-base font-medium text-fg-default dark:text-dark-fg-default hover:bg-neutral-100 dark:hover:bg-neutral-700">
              Settings
            </Link>
            <button on:click={handleLogout} class="w-full text-left block px-3 py-2 rounded-md text-base font-medium text-red-700 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30 hover:text-red-800 dark:hover:text-red-300 flex items-center">
              {@html logoutIcon} Logout
            </button>
          {:else}
            <Link to="/login" on:click={closeMenu} class="block px-3 py-2 rounded-md text-base font-medium text-fg-default dark:text-dark-fg-default hover:bg-neutral-100 dark:hover:bg-neutral-700 flex items-center">
              {@html loginIcon} Login
            </Link>
            <Link to="/register" on:click={closeMenu} class="block px-3 py-2 rounded-md text-base font-medium text-fg-default dark:text-dark-fg-default hover:bg-neutral-100 dark:hover:bg-neutral-700 flex items-center">
              {@html registerIcon} Register
            </Link>
          {/if}
        </div>
      </div>
    </div>
  {/if}
</header>
