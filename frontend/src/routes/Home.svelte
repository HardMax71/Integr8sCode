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

  <!-- HERO SECTION - Enhanced responsiveness -->
  <section class="hero-section relative isolate bg-bg-default dark:bg-dark-bg-default min-h-screen flex items-center justify-center px-4 sm:px-6 lg:px-8 xl:px-12 2xl:px-20">
     <div class="relative z-10 text-center w-full">
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

  <!-- FEATURES SECTION - Full width utilization -->
  <section class="bg-bg-default dark:bg-dark-bg-default py-16 sm:py-20 lg:py-28 px-4 sm:px-6 lg:px-8 xl:px-12 2xl:px-20">
    <div class="mx-auto max-w-full text-center mb-12 sm:mb-16">
         <h2 class="text-sm sm:text-base font-semibold leading-7 text-primary dark:text-primary-light animate-flyIn uppercase tracking-wider" style="--fly-delay: 600ms;">Core Features</h2>
         <p class="mt-2 text-2xl sm:text-3xl lg:text-4xl font-bold tracking-tight text-fg-default dark:text-dark-fg-default animate-flyIn" style="--fly-delay: 700ms;">
             Everything you need for quick execution.
         </p>
         <div class="mx-auto mt-6 w-24 h-1 bg-gradient-to-r from-transparent via-primary to-transparent animate-flyIn" style="--fly-delay: 800ms;"></div>
    </div>

    <!-- Responsive grid with better space utilization -->
    <div class="mx-auto max-w-full 2xl:max-w-screen-2xl grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6 lg:gap-8 xl:gap-10">
     {#each features as feature, i}
       <div class="feature-card relative flex flex-col items-start text-left p-6 sm:p-8 lg:p-10 bg-bg-alt dark:bg-dark-bg-alt rounded-2xl shadow-xl border border-border-default/50 dark:border-dark-border-default/30 transition-all duration-500 ease-out-expo hover:shadow-2xl hover:border-primary/50 dark:hover:border-primary/60 hover:-translate-y-2 animate-flyIn h-full overflow-hidden group"
            style="--fly-y: 30px; --fly-delay: {800 + i * 150}ms;">
         <!-- Number accent -->
         <div class="absolute top-6 right-6 text-5xl font-bold text-primary/10 dark:text-primary/20 select-none group-hover:text-primary/20 dark:group-hover:text-primary/30 transition-colors duration-500">
           0{i + 1}
         </div>

         <!-- Gradient overlay for depth -->
         <div class="absolute inset-0 bg-gradient-to-br from-primary/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500"></div>

         <!-- Animated background pattern -->
         <div class="absolute -right-8 -top-8 w-32 h-32 bg-primary/10 rounded-full blur-3xl opacity-0 group-hover:opacity-50 transition-all duration-700 group-hover:scale-150"></div>

         <!-- Content with relative positioning -->
         <div class="relative z-10">
           <div class="icon-wrapper flex h-14 w-14 sm:h-16 sm:w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/20 to-primary/10 dark:from-primary/30 dark:to-primary/15 text-primary dark:text-primary-light mb-6 shadow-lg group-hover:shadow-primary/25 transition-all duration-500 group-hover:scale-110 group-hover:rotate-3">
              {@html feature.icon}
           </div>
           <h3 class="text-lg sm:text-xl font-bold leading-7 sm:leading-8 text-fg-default dark:text-dark-fg-default mb-3 group-hover:text-primary dark:group-hover:text-primary-light transition-colors duration-300">{feature.title}</h3>
           <p class="flex-grow text-sm sm:text-base leading-6 sm:leading-7 text-fg-muted dark:text-dark-fg-muted group-hover:text-fg-default dark:group-hover:text-dark-fg-muted transition-colors duration-300">{feature.content}</p>

           <!-- Subtle bottom accent -->
           <div class="absolute bottom-0 left-0 right-0 h-1 bg-gradient-to-r from-transparent via-primary/30 to-transparent transform scale-x-0 group-hover:scale-x-100 transition-transform duration-500"></div>
         </div>
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

    /* Feature card enhancements */
    .feature-card {
        position: relative;
        background: theme('colors.bg-alt');
        backdrop-filter: blur(10px);
    }

    .dark .feature-card {
        background: theme('colors.dark-bg-alt');
    }

    .feature-card::before {
        content: '';
        position: absolute;
        inset: -2px;
        background: linear-gradient(135deg,
            theme('colors.primary.DEFAULT') 0%,
            transparent 40%,
            transparent 60%,
            theme('colors.secondary.DEFAULT') 100%);
        border-radius: 1rem;
        opacity: 0;
        transition: opacity 0.5s cubic-bezier(0.16, 1, 0.3, 1);
        z-index: -1;
    }

    .feature-card:hover::before {
        opacity: 0.2;
    }

    .icon-wrapper {
        position: relative;
    }

    .icon-wrapper::after {
        content: '';
        position: absolute;
        inset: -4px;
        background: radial-gradient(circle, theme('colors.primary.DEFAULT') 0%, transparent 70%);
        opacity: 0;
        border-radius: 1rem;
        transition: opacity 0.5s ease;
        z-index: -1;
    }

    .group:hover .icon-wrapper::after {
        opacity: 0.3;
    }

    .icon-wrapper svg {
        transition: transform 0.5s cubic-bezier(0.16, 1, 0.3, 1);
    }

    .group:hover .icon-wrapper svg {
        transform: scale(1.1);
    }

    /* Subtle floating animation for icons */
    @keyframes icon-float {
        0%, 100% { transform: translateY(0); }
        50% { transform: translateY(-4px); }
    }

    .group:hover .icon-wrapper {
        animation: icon-float 2s ease-in-out infinite;
    }

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
</style>