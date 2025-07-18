<script>
  import { Link, navigate } from "svelte-routing";
  import { isAuthenticated, username, logout as authLogout } from "../stores/auth.js";
  import { theme, toggleTheme } from "../stores/theme.js";
  import { fade } from 'svelte/transition';
  import { onMount, onDestroy } from 'svelte';

  let isMenuActive = false;
  let isMobile;
  let resizeListener;

  const sunIcon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"></path></svg>`;
  const moonIcon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"></path></svg>`;
  const menuIcon = `<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"></path></svg>`;
  const closeIcon = `<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>`;
  const logoIcon = `<svg class="h-8 w-8 text-primary group-hover:text-primary-light transition-colors duration-200" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"></path></svg>`;
  const loginIcon = `<svg class="w-5 h-5 mr-2 -ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1"></path></svg>`;
  const registerIcon = `<svg class="w-5 h-5 mr-2 -ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z"></path></svg>`;
  const logoutIcon = `<svg class="w-5 h-5 mr-2 -ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"></path></svg>`;


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
  }

  async function handleLogout() {
    await authLogout();
    closeMenu();
    navigate('/login');
  }

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

<header class="fixed top-0 left-0 right-0 bg-bg-alt/80 dark:bg-dark-bg-alt/80 backdrop-blur-md border-b border-border-default dark:border-dark-border-default shadow-sm z-50 transition-colors duration-300 h-16">
  <div class="app-container h-full">
    <nav class="flex items-center justify-between h-full">
      {#if logoIcon}
        <div class="flex items-center flex-shrink-0">
          <Link to="/" on:click={closeMenu} class="flex items-center space-x-2 group">
            {@html logoIcon}
            <span class="font-semibold text-xl tracking-tight text-fg-default dark:text-dark-fg-default group-hover:text-primary dark:group-hover:text-primary-light transition-colors duration-200">
            Integr8sCode
          </span>
          </Link>
        </div>
      {/if}

      <div class="hidden lg:flex items-center space-x-6 flex-grow justify-center">
         <div></div>
      </div>

      <div class="flex items-center space-x-3">
        <button on:click={toggleTheme} title="Toggle theme" class="btn btn-ghost btn-icon text-fg-muted dark:text-dark-fg-muted hover:text-fg-default dark:hover:text-dark-fg-default">
          {#if $theme === 'dark'}
            {@html sunIcon}
          {:else}
            {@html moonIcon}
          {/if}
        </button>

        <div class="hidden lg:flex items-center space-x-3">
          {#if $isAuthenticated}
            <span class="text-sm text-fg-muted dark:text-dark-fg-muted hidden xl:inline">Welcome, <span class="font-medium text-fg-default dark:text-dark-fg-default">{$username}!</span></span>
            <button on:click={handleLogout} class="btn btn-secondary-outline btn-sm">
              Logout
            </button>
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
               <div class="text-xs text-fg-muted dark:text-dark-fg-muted">Logged in</div>
            </div>
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