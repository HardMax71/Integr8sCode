<script>
  import { Link } from "svelte-routing";
  import { authToken, username, logout } from "../stores/auth.js";
  import { fade } from 'svelte/transition';
  import { onMount } from 'svelte';

  let isMenuActive = false;
  let isMobile;

  onMount(() => {
    const checkMobile = () => {
      isMobile = window.innerWidth < 1024;
      if (!isMobile) {
        isMenuActive = false; // Close the menu when resizing to desktop
      }
    };
    checkMobile();
    window.addEventListener('resize', checkMobile);
    return () => window.removeEventListener('resize', checkMobile);
  });

  function toggleMenu() {
    isMenuActive = !isMenuActive;
  }

  function closeMenu() {
    isMenuActive = false;
  }
</script>

<header class="fixed top-0 left-0 right-0 bg-gray-800 text-white shadow-md z-50">
  <div class="container mx-auto px-4 py-3">
    <nav class="flex items-center justify-between flex-wrap">
      <!-- Logo -->
      <div class="flex items-center flex-shrink-0 mr-6">
        <Link to="/" on:click={closeMenu} class="font-semibold text-2xl tracking-tight hover:text-yellow-400 transition-colors duration-200">
          Integr8sCode
        </Link>
      </div>
      <!-- Hamburger Menu Button -->
      <div class="block lg:hidden">
        <button on:click={toggleMenu}
                class="flex items-center px-3 py-2 border rounded text-white border-white hover:text-yellow-400 hover:border-yellow-400 transition-colors duration-200">
          <svg class="fill-current h-5 w-5" viewBox="0 0 20 20">
            <title>Menu</title>
            <path d="M0 3h20v2H0V3zM0 9h20v2H0V9zM0 15h20v2H0v-2z"/>
          </svg>
        </button>
      </div>
      <!-- Navigation Links -->
      <div class={`w-full ${isMenuActive ? 'block' : 'hidden'} lg:block lg:flex lg:items-center lg:w-auto`}>
        <div class="text-lg lg:text-sm lg:flex-grow mt-4 lg:mt-0 text-center lg:text-left">
          <Link to="/" on:click={closeMenu} class="block lg:inline-block hover:text-yellow-400 lg:mr-4 mb-2 lg:mb-0 transition-colors duration-200">
            Home
          </Link>
          {#if $authToken}
            <Link to="/editor" on:click={closeMenu} class="block lg:inline-block hover:text-yellow-400 lg:mr-4 mb-2 lg:mb-0 transition-colors duration-200">
              Code Editor
            </Link>
          {/if}
        </div>
        <!-- Authentication Buttons -->
        <div class="mt-4 lg:mt-0 flex flex-col lg:flex-row items-center">
          {#if $authToken}
            <span class="text-yellow-400 text-lg lg:text-sm mb-2 lg:mb-0 lg:mr-4">Welcome, {$username}!</span>
            <button on:click={() => { logout(); closeMenu(); }}
                    class="w-full lg:w-auto text-center text-base lg:text-sm px-4 py-2 leading-none border rounded text-white border-white hover:border-transparent hover:text-gray-800 hover:bg-white transition-colors duration-200"
                    in:fade>
              Logout
            </button>
          {:else}
            <Link to="/login"
                  on:click={closeMenu}
                  class="w-full lg:w-auto text-center text-base lg:text-sm px-4 py-2 leading-none border rounded text-white border-white hover:border-transparent hover:text-gray-800 hover:bg-white mb-2 lg:mb-0 lg:mr-2 transition-colors duration-200">
              Login
            </Link>
            <Link to="/register"
                  on:click={closeMenu}
                  class="w-full lg:w-auto text-center text-base lg:text-sm px-4 py-2 leading-none border rounded text-yellow-400 border-yellow-400 hover:border-transparent hover:text-gray-800 hover:bg-yellow-400 transition-colors duration-200">
              Register
            </Link>
          {/if}
        </div>
      </div>
    </nav>
  </div>
</header>
