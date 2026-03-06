<script lang="ts">
    import { route } from '@mateothegreat/svelte5-router';
    import { onMount, type Component } from 'svelte';
    import { updateMetaTags, pageMeta } from '$utils/meta';
    import { Zap, ShieldCheck, Clock } from '@lucide/svelte';

    const features: { icon: Component; title: string; content: string }[] = [
        {
            icon: Zap,
            title: 'Instant Execution',
            content: 'Run code online effortlessly in isolated Kubernetes pods with near-native speed.',
        },
        {
            icon: ShieldCheck,
            title: 'Secure & Efficient',
            content: 'Strict resource limits (CPU, Memory, Time) and network restrictions ensure safe code execution.',
        },
        {
            icon: Clock,
            title: 'Real-time Results',
            content: 'Get immediate feedback with live execution status updates and detailed output upon completion.',
        },
    ];

    let ready = $state(false);
    onMount(() => {
        ready = true;
        updateMetaTags(pageMeta.home.title, pageMeta.home.description);
    });
</script>

{#if ready}
    <div class="bg-bg-default dark:bg-dark-bg-default">
        <!-- HERO SECTION -->
        <section
            class="gradient-bg relative isolate overflow-x-clip min-h-screen -mt-16 pt-16 flex items-center justify-center px-4 sm:px-6 lg:px-8 xl:px-12 2xl:px-20"
        >
            <div class="relative z-10 text-center w-full -mt-4 sm:-mt-6">
                <div class="hero-animate-fly-in" style="--fly-y: -20px; --fly-delay: 100ms;">
                    <h1
                        class="mx-auto max-w-full xl:max-w-7xl text-3xl sm:text-4xl md:text-5xl lg:text-6xl xl:text-7xl font-bold tracking-tight text-fg-default dark:text-dark-fg-default leading-tight! px-2 sm:px-4"
                    >
                        Code, Run, <span class="text-primary dark:text-primary-light">Integrate</span>. Instantly.
                    </h1>
                </div>
                <div class="hero-animate-fly-in" style="--fly-y: 15px; --fly-delay: 300ms;">
                    <p
                        class="mx-auto mt-4 sm:mt-6 max-w-full lg:max-w-4xl xl:max-w-5xl text-base sm:text-lg md:text-xl leading-relaxed text-fg-muted dark:text-dark-fg-muted px-4 sm:px-8 lg:px-12"
                    >
                        Welcome to Integr8sCode – the seamless online execution environment built on Kubernetes. Paste
                        your script, hit run, and get results securely and efficiently.
                    </p>
                </div>
                <div class="mt-8 sm:mt-10 hero-animate-fly-in" style="--fly-y: 15px; --fly-delay: 500ms;">
                    <a
                        href="/editor"
                        use:route
                        class="btn btn-primary btn-lg px-6 sm:px-8 py-2.5 sm:py-3 text-sm sm:text-base font-semibold shadow-lg hover:shadow-primary/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary transition-all duration-300 ease-out-expo hover:-translate-y-0.5 hover:text-white"
                    >
                        Start Coding Now
                    </a>
                </div>
            </div>
        </section>

        <!-- FEATURES SECTION -->
        <section class="pt-10 sm:pt-14 lg:pt-16 pb-16 sm:pb-20 lg:pb-28 px-4 sm:px-6 lg:px-8 xl:px-12 2xl:px-20">
            <div class="mx-auto max-w-full text-center mb-12 sm:mb-16">
                <h2
                    class="text-sm sm:text-base font-semibold leading-7 text-primary-dark dark:text-primary-light hero-animate-fly-in uppercase tracking-wider"
                    style="--fly-delay: 600ms;"
                >
                    Core Features
                </h2>
                <p
                    class="mt-2 text-2xl sm:text-3xl lg:text-4xl font-bold tracking-tight text-fg-default dark:text-dark-fg-default hero-animate-fly-in"
                    style="--fly-delay: 700ms;"
                >
                    Everything you need for quick execution.
                </p>
            </div>

            <div
                class="mx-auto max-w-5xl grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-5 lg:gap-6 features-grid"
            >
                {#each features as feature, i}
                    {@const Icon = feature.icon}
                    <div
                        class="feature-card group relative flex flex-col items-start text-left pl-5 pr-5 py-5 sm:pl-6 sm:pr-6 sm:py-6 bg-bg-alt dark:bg-dark-bg-alt rounded-xl border border-border-default/50 dark:border-dark-border-default/50 shadow-xs transition-all duration-300 hover:shadow-lg hover:-translate-y-0.5 hover:border-primary/40 hero-animate-fly-in h-full"
                        style="--fly-y: 24px; --fly-delay: {800 + i * 120}ms;"
                    >
                        <h3
                            class="flex items-center gap-2 text-lg sm:text-xl font-semibold leading-7 text-fg-default dark:text-dark-fg-default mb-2 transition-colors duration-200 group-hover:text-primary dark:group-hover:text-primary-light"
                        >
                            <Icon class="h-5 w-5 shrink-0 text-primary dark:text-primary-light" />
                            {feature.title}
                        </h3>
                        <p class="text-sm sm:text-base leading-6 sm:leading-7 text-fg-muted dark:text-dark-fg-muted">
                            {feature.content}
                        </p>
                    </div>
                {/each}
            </div>
        </section>
    </div>
{/if}
