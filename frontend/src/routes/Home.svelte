<script>
  import { Link } from "svelte-routing";
  import { fade, fly } from "svelte/transition";
  import { onMount } from 'svelte';

  const boltIcon = `<svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>`;
  const shieldCheckIcon = `<svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"></path></svg>`;
  const clockIcon = `<svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`;

  const features = [
    { icon: boltIcon, title: "Instant Execution", content: "Run code online effortlessly in isolated Kubernetes pods with near-native speed." },
    { icon: shieldCheckIcon, title: "Secure & Efficient", content: "Strict resource limits (CPU, Memory, Time) and network restrictions ensure safe code execution." },
    { icon: clockIcon, title: "Real-time Results", content: "Get immediate feedback with live execution status updates and detailed output upon completion." }
  ];

  let ready = false;
  onMount(() => ready = true);
</script>

{#if ready}
<div class="overflow-x-hidden">

  <section class="hero-section relative isolate overflow-hidden bg-bg-default dark:bg-dark-bg-default px-6 pt-24 pb-16 sm:pt-32 sm:pb-24 lg:px-8 text-center">
     <div class="mx-auto max-w-2xl relative z-10">
        <div class="animate-flyIn" style="--fly-y: -20px; --fly-delay: 100ms;">
             <h1 class="text-4xl font-bold tracking-tight text-fg-default dark:text-dark-fg-default sm:text-6xl !leading-tight">
                 Code, Run, <span class="text-primary dark:text-primary-light">Integrate</span>. Instantly.
             </h1>
        </div>
        <div class="animate-flyIn" style="--fly-y: 15px; --fly-delay: 300ms;">
            <p class="mt-6 text-lg leading-8 text-fg-muted dark:text-dark-fg-muted">
                Welcome to Integr8sCode – the seamless online Python execution environment built on Kubernetes.
                Paste your script, hit run, and get results securely and efficiently.
            </p>
        </div>
        <div class="mt-10 animate-flyIn" style="--fly-y: 15px; --fly-delay: 500ms;">
            <Link to="/editor" class="btn btn-primary btn-lg px-8 py-3 text-base font-semibold shadow-lg hover:shadow-primary/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary transition-all duration-300 ease-out-expo hover:-translate-y-0.5">
                Start Coding Now
            </Link>
        </div>
     </div>
  </section>

  <section class="bg-bg-alt dark:bg-dark-bg-alt py-16 sm:py-24 lg:py-32">
    <div class="app-container">
        <div class="mx-auto max-w-xl text-center mb-12 lg:mb-16">
             <h2 class="text-base font-semibold leading-7 text-primary dark:text-primary-light animate-flyIn" style="--fly-delay: 600ms;">Core Features</h2>
             <p class="mt-2 text-3xl font-bold tracking-tight text-fg-default dark:text-dark-fg-default sm:text-4xl animate-flyIn" style="--fly-delay: 700ms;">
                 Everything you need for quick execution.
             </p>
        </div>
       <div class="grid grid-cols-1 gap-x-6 gap-y-10 md:grid-cols-3 md:gap-x-8 md:gap-y-12 lg:gap-x-10">
         {#each features as feature, i}
           <div class="relative flex flex-col items-start text-left p-6 bg-bg-default dark:bg-dark-bg-default rounded-xl shadow-sm border border-border-default dark:border-dark-border-default transition-all duration-300 ease-out-expo hover:shadow-lg hover:border-primary/30 dark:hover:border-primary/40 hover:-translate-y-1 animate-flyIn"
                style="--fly-y: 20px; --fly-delay: {800 + i * 150}ms;">
             <div class="flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10 dark:bg-primary/20 text-primary dark:text-primary-light mb-5">
                {@html feature.icon}
             </div>
             <h3 class="text-lg font-semibold leading-7 text-fg-default dark:text-dark-fg-default">{feature.title}</h3>
             <p class="mt-2 flex-grow text-sm leading-6 text-fg-muted dark:text-dark-fg-muted">{feature.content}</p>
           </div>
         {/each}
       </div>
    </div>
  </section>

</div>
{/if}

<style lang="postcss">
    @keyframes flyIn {
        from { opacity: 0; transform: translateY(var(--fly-y, 20px)); }
        to { opacity: 1; transform: translateY(0); }
    }

    .animate-flyIn {
        animation: flyIn 0.5s cubic-bezier(0.16, 1, 0.3, 1) both;
        animation-delay: var(--fly-delay, 0s);
    }

    [style*="--fly-delay"] {
        opacity: 0;
    }

    /* Animated Shapes Background */
    @keyframes shape-float-1 {
      0% { transform: translate(0, 0) rotate(0deg) scale(1); }
      25% { transform: translate(-10px, 15px) rotate(10deg) scale(1.05); }
      50% { transform: translate(5px, -10px) rotate(-5deg) scale(1); }
      75% { transform: translate(10px, 5px) rotate(5deg) scale(0.95); }
      100% { transform: translate(0, 0) rotate(0deg) scale(1); }
    }
    @keyframes shape-float-2 {
       0% { transform: translate(0, 0) rotate(0deg) scale(1); }
       25% { transform: translate(15px, -5px) rotate(-8deg) scale(0.98); }
       50% { transform: translate(-5px, 10px) rotate(12deg) scale(1.02); }
       75% { transform: translate(-10px, -15px) rotate(-3deg) scale(1); }
       100% { transform: translate(0, 0) rotate(0deg) scale(1); }
    }

    .hero-section::before,
    .hero-section::after {
        content: '';
        @apply absolute -z-10 rounded-full;
        filter: blur(60px); /* Slightly less blur than gradient */
        opacity: 0.15;
        will-change: transform;
    }
     .dark .hero-section::before,
     .dark .hero-section::after {
         opacity: 0.1; /* Even more subtle in dark mode */
          filter: blur(70px);
     }

    /* Shape 1: Large Circle (Primary Color) */
    .hero-section::before {
        width: 50rem; height: 50rem;
        left: -20rem; top: -20rem;
        background-color: theme('colors.primary.light');
        animation: shape-float-1 35s ease-in-out infinite;
    }
     .dark .hero-section::before {
        background-color: theme('colors.primary.DEFAULT');
     }


    /* Shape 2: Smaller Ellipse (Secondary Color) */
    .hero-section::after {
       width: 40rem; height: 30rem; /* Elliptical */
       right: -15rem; bottom: -10rem;
       border-radius: 60% 40% 30% 70% / 60% 30% 70% 40%; /* Organic shape */
       background-color: theme('colors.secondary.DEFAULT');
       animation: shape-float-2 45s ease-in-out infinite;
    }
     .dark .hero-section::after {
         background-color: theme('colors.secondary.dark');
          border-radius: 30% 70% 70% 30% / 30% 30% 70% 70%; /* Different shape */
     }


     .hero-section > div {
         @apply relative z-10;
     }
</style>