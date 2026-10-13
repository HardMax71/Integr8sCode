<script lang="ts">
    import { resolve } from '$app/paths';
    import { onMount, type Component } from 'svelte';
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
    });
</script>

<svelte:head>
    <title>Home - Integr8sCode</title>
    <meta
        name="description"
        content="Integr8sCode - Write, compile, and manage code directly in your browser with our powerful online development environment"
    />
</svelte:head>

{#if ready}
    <div class="bg-page">
        <section
            class="gradient-bg relative isolate overflow-x-clip min-h-dvh -mt-16 pt-16 flex items-center justify-center px-4 sm:px-6 lg:px-8"
        >
            <div class="relative z-10 text-center w-full -mt-4 sm:-mt-6">
                <div class="hero-animate-fly-in" style="--fly-y: -20px; --fly-delay: 100ms;">
                    <h1 class="mx-auto max-w-7xl text-4xl sm:text-5xl lg:text-7xl tracking-tight leading-tight px-2">
                        Code, Run, <span class="text-accent">Integrate</span>. Instantly.
                    </h1>
                </div>
                <div class="hero-animate-fly-in" style="--fly-y: 15px; --fly-delay: 300ms;">
                    <p class="mx-auto mt-6 max-w-4xl text-lg sm:text-xl leading-relaxed text-fg-muted px-4">
                        Welcome to Integr8sCode – the seamless online execution environment built on Kubernetes. Paste
                        your script, hit run, and get results securely and efficiently.
                    </p>
                </div>
                <div class="mt-8 sm:mt-10 hero-animate-fly-in" style="--fly-y: 15px; --fly-delay: 500ms;">
                    <a href={resolve('/(auth)/editor')} class="btn btn-primary btn-lg font-semibold shadow-lg">
                        Start Coding Now
                    </a>
                </div>
            </div>
        </section>

        <section class="app-container pt-14 pb-20 lg:pb-28">
            <div class="text-center mb-12 sm:mb-16">
                <p class="section-label text-sm text-accent hero-animate-fly-in" style="--fly-delay: 600ms;">
                    Core Features
                </p>
                <h2
                    class="mt-2 text-2xl sm:text-3xl lg:text-4xl font-bold tracking-tight hero-animate-fly-in"
                    style="--fly-delay: 700ms;"
                >
                    Everything you need for quick execution.
                </h2>
            </div>

            <div class="features-grid mx-auto max-w-5xl grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
                {#each features as feature, i (feature.title)}
                    {@const Icon = feature.icon}
                    <div
                        class="feature-card group hero-animate-fly-in"
                        style="--fly-y: 24px; --fly-delay: {800 + i * 120}ms;"
                    >
                        <h3
                            class="flex items-center gap-2 text-lg sm:text-xl font-semibold mb-2 transition-colors group-hover:text-accent"
                        >
                            <Icon class="size-5 shrink-0 text-accent" />
                            {feature.title}
                        </h3>
                        <p class="text-fg-muted">
                            {feature.content}
                        </p>
                    </div>
                {/each}
            </div>
        </section>
    </div>
{/if}
