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
    };
    checkMobile();
    window.addEventListener('resize', checkMobile);
    return () => window.removeEventListener('resize', checkMobile);
  });

  function toggleMenu() {
    isMenuActive = !isMenuActive;
  }
</script>

<header class="bg-gray-800 text-gray-100 shadow-md">
  <div class="container mx-auto px-4 py-3">
    <nav class="flex items-center justify-between flex-wrap">
      <div class="flex items-center flex-shrink-0 mr-6">
        <Link to="/" class="font-semibold text-xl tracking-tight hover:text-yellow-400 transition-colors duration-200">
          Integr8sCode
        </Link>
      </div>
      <div class="block lg:hidden">
        <button on:click={toggleMenu} class="flex items-center px-3 py-2 border rounded text-gray-300 border-gray-400 hover:text-white hover:border-white transition-colors duration-200">
          <svg class="fill-current h-3 w-3" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
            <title>Menu</title>
            <path d="M0 3h20v2H0V3zm0 6h20v2H0V9zm0 6h20v2H0v-2z"/>
          </svg>
        </button>
      </div>
      <div class={`w-full flex-grow lg:flex lg:items-center lg:w-auto ${isMenuActive ? 'block' : 'hidden'}`}>
        <div class="text-sm lg:flex-grow">
          <Link to="/" class="block mt-4 lg:inline-block lg:mt-0 hover:text-yellow-400 mr-4 transition-colors duration-200">
            Home
          </Link>
          <Link to="/editor" class="block mt-4 lg:inline-block lg:mt-0 hover:text-yellow-400 mr-4 transition-colors duration-200">
            Code Editor
          </Link>
        </div>
        <div class="mt-4 lg:mt-0">
          {#if $authToken}
            <span class="text-yellow-400 mr-4">Welcome, {$username}!</span>
            <button on:click={logout} class="inline-block text-sm px-4 py-2 leading-none border rounded text-white border-white hover:border-transparent hover:text-gray-800 hover:bg-white transition-colors duration-200" in:fade>
              Logout
            </button>
          {:else}
            <Link to="/login" class="inline-block text-sm px-4 py-2 leading-none border rounded text-white border-white hover:border-transparent hover:text-gray-800 hover:bg-white mt-4 lg:mt-0 mr-2 transition-colors duration-200">
              Login
            </Link>
            <Link to="/register" class="inline-block text-sm px-4 py-2 leading-none border rounded text-yellow-400 border-yellow-400 hover:border-transparent hover:text-gray-800 hover:bg-yellow-400 mt-4 lg:mt-0 transition-colors duration-200">
              Register
            </Link>
          {/if}
        </div>
      </div>
    </nav>
  </div>
</header>