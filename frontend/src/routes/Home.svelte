<script>
  import { Link } from "svelte-routing";
  import { fade, fly } from "svelte/transition";
  import { onMount } from 'svelte';
  import { updateMetaTags, pageMeta } from '../utils/meta.js';

  const boltIcon = `<svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>`;
  const shieldCheckIcon = `<svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"></path></svg>`;
  const clockIcon = `<svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`;

  const features = [
    { icon: boltIcon, title: "Instant Execution", content: "Run code online effortlessly in isolated Kubernetes pods with near-native speed." },
    { icon: shieldCheckIcon, title: "Secure & Efficient", content: "Strict resource limits (CPU, Memory, Time) and network restrictions ensure safe code execution." },
    { icon: clockIcon, title: "Real-time Results", content: "Get immediate feedback with live execution status updates and detailed output upon completion." }
  ];

  let ready = false;
  onMount(() => {
    ready = true;
    updateMetaTags(pageMeta.home.title, pageMeta.home.description);
  });
</script>

{#if ready}
<div class="overflow-x-hidden">

  <!-- HERO SECTION - Enhanced responsiveness -->
  <section class="hero-section relative isolate bg-bg-default dark:bg-dark-bg-default min-h-[80vh] flex items-center justify-center px-4 sm:px-6 lg:px-8 xl:px-12 2xl:px-20">
     <div class="relative z-10 text-center w-full -mt-4 sm:-mt-6">
        <div class="animate-flyIn" style="--fly-y: -20px; --fly-delay: 100ms;">
             <h1 class="mx-auto max-w-full xl:max-w-7xl text-3xl sm:text-4xl md:text-5xl lg:text-6xl xl:text-7xl font-bold tracking-tight text-fg-default dark:text-dark-fg-default !leading-tight px-2 sm:px-4">
                 Code, Run, <span class="text-primary dark:text-primary-light">Integrate</span>. Instantly.
             </h1>
        </div>
        <div class="animate-flyIn" style="--fly-y: 15px; --fly-delay: 300ms;">
            <p class="mx-auto mt-4 sm:mt-6 max-w-full lg:max-w-4xl xl:max-w-5xl text-base sm:text-lg md:text-xl leading-relaxed text-fg-muted dark:text-dark-fg-muted px-4 sm:px-8 lg:px-12">
                Welcome to Integr8sCode – the seamless online execution environment built on Kubernetes.
                Paste your script, hit run, and get results securely and efficiently.
            </p>
        </div>
        <div class="mt-8 sm:mt-10 animate-flyIn" style="--fly-y: 15px; --fly-delay: 500ms;">
            <Link to="/editor" class="btn btn-primary btn-lg px-6 sm:px-8 py-2.5 sm:py-3 text-sm sm:text-base font-semibold shadow-lg hover:shadow-primary/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary transition-all duration-300 ease-out-expo hover:-translate-y-0.5 hover:text-white">
                Start Coding Now
            </Link>
        </div>
     </div>
  </section>

  <!-- FEATURES SECTION - Simplified, adaptive, on-brand -->
  <section class="bg-bg-default dark:bg-dark-bg-default py-16 sm:py-20 lg:py-28 px-4 sm:px-6 lg:px-8 xl:px-12 2xl:px-20">
    <div class="mx-auto max-w-full text-center mb-12 sm:mb-16">
         <h2 class="text-sm sm:text-base font-semibold leading-7 text-primary-dark dark:text-primary-light animate-flyIn uppercase tracking-wider" style="--fly-delay: 600ms;">Core Features</h2>
         <p class="mt-2 text-2xl sm:text-3xl lg:text-4xl font-bold tracking-tight text-fg-default dark:text-dark-fg-default animate-flyIn" style="--fly-delay: 700ms;">
             Everything you need for quick execution.
         </p>
         <div class="mx-auto mt-6 w-24 h-1 bg-gradient-to-r from-transparent via-primary to-transparent animate-flyIn" style="--fly-delay: 800ms;"></div>
    </div>

    <!-- Responsive grid with centered lone last item at 2-col breakpoint -->
    <div class="mx-auto max-w-5xl grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 sm:gap-7 lg:gap-8 features-grid">
      {#each features as feature, i}
        <div class="feature-card group relative flex flex-col items-start text-left p-6 sm:p-8 bg-bg-alt dark:bg-dark-bg-alt rounded-xl border border-border-default/50 dark:border-dark-border-default/50 shadow-sm transition-transform duration-300 hover:shadow-lg hover:-translate-y-1 hover:border-primary/40 animate-flyIn h-full"
             style="--fly-y: 24px; --fly-delay: {800 + i * 120}ms;">
          <!-- Icon -->
          <div class="flex h-12 w-12 sm:h-14 sm:w-14 items-center justify-center rounded-full bg-primary/10 text-primary dark:text-primary-light ring-1 ring-primary/20 mb-5 transition-transform duration-300 group-hover:scale-110 group-hover:ring-primary/40">
            {@html feature.icon}
          </div>
          <h3 class="text-lg sm:text-xl font-semibold leading-7 sm:leading-8 text-fg-default dark:text-dark-fg-default mb-2 transition-colors duration-200 group-hover:text-primary dark:group-hover:text-primary-light">{feature.title}</h3>
          <p class="flex-grow text-sm sm:text-base leading-6 sm:leading-7 text-fg-muted dark:text-dark-fg-muted">{feature.content}</p>
          <div class="mt-6 h-0.5 w-full origin-left transform scale-x-0 bg-gradient-to-r from-transparent via-primary/50 to-transparent transition-transform duration-300 group-hover:scale-x-100"></div>
        </div>
      {/each}
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

    /* Animated Shapes Background - Responsive sizing */
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

    /* Feature card: simplified to align with general style */
    .feature-card { position: relative; }

    .hero-section::before,
    .hero-section::after {
        content: '';
        @apply absolute -z-10 rounded-full;
        filter: blur(60px);
        opacity: 0.15;
        will-change: transform;
    }
     .dark .hero-section::before,
     .dark .hero-section::after {
         opacity: 0.1;
          filter: blur(70px);
     }

    .hero-section::before {
        width: 25rem; height: 25rem;
        left: -10rem; top: -10rem;
        background-color: theme('colors.primary.light');
        animation: shape-float-1 35s ease-in-out infinite;
    }

    /* Responsive background shapes */
    @media (min-width: 640px) {
        .hero-section::before {
            width: 35rem; height: 35rem;
            left: -15rem; top: -15rem;
        }
    }

    @media (min-width: 1024px) {
        .hero-section::before {
            width: 50rem; height: 50rem;
            left: -20rem; top: -20rem;
        }
    }

     .dark .hero-section::before {
        background-color: theme('colors.primary.DEFAULT');
     }

    .hero-section::after {
       width: 20rem; height: 15rem;
       right: -10rem; bottom: -5rem;
       border-radius: 60% 40% 30% 70% / 60% 30% 70% 40%;
       background-color: theme('colors.secondary.DEFAULT');
       animation: shape-float-2 45s ease-in-out infinite;
    }

    @media (min-width: 640px) {
        .hero-section::after {
            width: 30rem; height: 22rem;
            right: -12rem; bottom: -7rem;
        }
    }

    @media (min-width: 1024px) {
        .hero-section::after {
            width: 40rem; height: 30rem;
            right: -15rem; bottom: -10rem;
        }
    }

     .dark .hero-section::after {
         background-color: theme('colors.secondary.dark');
          border-radius: 30% 70% 70% 30% / 30% 30% 70% 70%;
     }

    /* Center a lone last card when grid has 2 columns (sm..lg) */
    @media (min-width: 640px) and (max-width: 1023.98px) {
      .features-grid > :last-child:nth-child(2n + 1) {
        grid-column: 1 / -1;
        justify-self: center;
        max-width: 36rem;
        width: 100%;
      }
    }
</style>
