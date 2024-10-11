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

<header class="bg-gray-800 text-white">
  <nav class="container mx-auto px-4 py-4 flex justify-between items-center">
    <Link to="/" class="text-xl font-bold">Integr8sCode</Link>

    <button class="lg:hidden" on:click={toggleMenu}>
      <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16m-7 6h7"></path>
      </svg>
    </button>

    <div class={`lg:flex ${isMenuActive ? 'block' : 'hidden'}`}>
      <Link to="/" class="block mt-4 lg:inline-block lg:mt-0 hover:text-gray-300 mr-4">Home</Link>
      <Link to="/editor" class="block mt-4 lg:inline-block lg:mt-0 hover:text-gray-300 mr-4">Code Editor</Link>

      {#if $authToken}
        <span class="block mt-4 lg:inline-block lg:mt-0 mr-4">Welcome, {$username}!</span>
        <button on:click={logout} class="block mt-4 lg:inline-block lg:mt-0 bg-red-500 hover:bg-red-600 text-white font-bold py-2 px-4 rounded" in:fade>Logout</button>
      {:else}
        <Link to="/login" class="block mt-4 lg:inline-block lg:mt-0 bg-blue-500 hover:bg-blue-600 text-white font-bold py-2 px-4 rounded mr-2">Login</Link>
        <Link to="/register" class="block mt-4 lg:inline-block lg:mt-0 bg-gray-500 hover:bg-gray-600 text-white font-bold py-2 px-4 rounded">Register</Link>
      {/if}
    </div>
  </nav>
</header>