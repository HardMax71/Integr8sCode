<script lang="ts">
  import { route } from "@mateothegreat/svelte5-router";
  import { fade, fly } from "svelte/transition";
  import { onMount, type Component } from 'svelte';
  import { updateMetaTags, pageMeta } from '$utils/meta';
  import { Zap, ShieldCheck, Clock } from '@lucide/svelte';

  const features: { icon: Component; title: string; content: string }[] = [
    { icon: Zap, title: "Instant Execution", content: "Run code online effortlessly in isolated Kubernetes pods with near-native speed." },
    { icon: ShieldCheck, title: "Secure & Efficient", content: "Strict resource limits (CPU, Memory, Time) and network restrictions ensure safe code execution." },
    { icon: Clock, title: "Real-time Results", content: "Get immediate feedback with live execution status updates and detailed output upon completion." }
  ];

  let ready = $state(false);
  onMount(() => {
    ready = true;
    updateMetaTags(pageMeta.home.title, pageMeta.home.description);
  });
</script>

{#if ready}
<div>

  <!-- HERO SECTION - Enhanced responsiveness -->
  <section class="hero-section relative isolate overflow-x-clip bg-bg-default dark:bg-dark-bg-default min-h-[80vh] flex items-center justify-center px-4 sm:px-6 lg:px-8 xl:px-12 2xl:px-20">
     <div class="relative z-10 text-center w-full -mt-4 sm:-mt-6">
        <div class="hero-animate-flyIn" style="--fly-y: -20px; --fly-delay: 100ms;">
             <h1 class="mx-auto max-w-full xl:max-w-7xl text-3xl sm:text-4xl md:text-5xl lg:text-6xl xl:text-7xl font-bold tracking-tight text-fg-default dark:text-dark-fg-default leading-tight! px-2 sm:px-4">
                 Code, Run, <span class="text-primary dark:text-primary-light">Integrate</span>. Instantly.
             </h1>
        </div>
        <div class="hero-animate-flyIn" style="--fly-y: 15px; --fly-delay: 300ms;">
            <p class="mx-auto mt-4 sm:mt-6 max-w-full lg:max-w-4xl xl:max-w-5xl text-base sm:text-lg md:text-xl leading-relaxed text-fg-muted dark:text-dark-fg-muted px-4 sm:px-8 lg:px-12">
                Welcome to Integr8sCode – the seamless online execution environment built on Kubernetes.
                Paste your script, hit run, and get results securely and efficiently.
            </p>
        </div>
        <div class="mt-8 sm:mt-10 hero-animate-flyIn" style="--fly-y: 15px; --fly-delay: 500ms;">
            <a href="/editor" use:route class="btn btn-primary btn-lg px-6 sm:px-8 py-2.5 sm:py-3 text-sm sm:text-base font-semibold shadow-lg hover:shadow-primary/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary transition-all duration-300 ease-out-expo hover:-translate-y-0.5 hover:text-white">
                Start Coding Now
            </a>
        </div>
     </div>
  </section>

  <!-- FEATURES SECTION - Simplified, adaptive, on-brand -->
  <section class="bg-bg-default dark:bg-dark-bg-default py-16 sm:py-20 lg:py-28 px-4 sm:px-6 lg:px-8 xl:px-12 2xl:px-20">
    <div class="mx-auto max-w-full text-center mb-12 sm:mb-16">
         <h2 class="text-sm sm:text-base font-semibold leading-7 text-primary-dark dark:text-primary-light hero-animate-flyIn uppercase tracking-wider" style="--fly-delay: 600ms;">Core Features</h2>
         <p class="mt-2 text-2xl sm:text-3xl lg:text-4xl font-bold tracking-tight text-fg-default dark:text-dark-fg-default hero-animate-flyIn" style="--fly-delay: 700ms;">
             Everything you need for quick execution.
         </p>
         <div class="mx-auto mt-6 w-24 h-1 bg-gradient-to-r from-transparent via-primary to-transparent hero-animate-flyIn" style="--fly-delay: 800ms;"></div>
    </div>

    <!-- Responsive grid with centered lone last item at 2-col breakpoint -->
    <div class="mx-auto max-w-5xl grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 sm:gap-7 lg:gap-8 features-grid">
      {#each features as feature, i}
        {@const Icon = feature.icon}
        <div class="feature-card group relative flex flex-col items-start text-left p-6 sm:p-8 bg-bg-alt dark:bg-dark-bg-alt rounded-xl border border-border-default/50 dark:border-dark-border-default/50 shadow-xs transition-transform duration-300 hover:shadow-lg hover:-translate-y-1 hover:border-primary/40 hero-animate-flyIn h-full"
             style="--fly-y: 24px; --fly-delay: {800 + i * 120}ms;">
          <!-- Icon -->
          <div class="flex h-12 w-12 sm:h-14 sm:w-14 items-center justify-center rounded-full bg-primary/10 text-primary dark:text-primary-light ring-1 ring-primary/20 mb-5 transition-transform duration-300 group-hover:scale-110 group-hover:ring-primary/40">
            <Icon class="h-6 w-6" />
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
