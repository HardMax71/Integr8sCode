<script>
    import { fade, fly } from 'svelte/transition';
    import { onMount } from 'svelte';

    const sections = [
        { icon: '🏗️', title: "Architecture", content: "Built with a Svelte frontend, FastAPI backend, and MongoDB database, all orchestrated with Kubernetes for robust performance." },
        { icon: '🔑', title: "Key Features", content: "User authentication, robust resource management, and isolated execution environments for enhanced security and efficiency." },
        { icon: '🔀', title: "Integrations", content: "Seamlessly integrated with Kubernetes for container orchestration and MongoDB for efficient data storage and retrieval." },
       ];

    let visible = false;
    onMount(() => { visible = true; });
</script>

{#if visible}
<div class="py-16 sm:py-24 lg:py-32" in:fade={{duration: 500}}>
        <!-- Page Title -->
        <div class="text-center mb-12 md:mb-16">
            <h1 class="text-4xl sm:text-5xl font-bold text-fg-default dark:text-dark-fg-default mb-3"
                in:fly={{y: -20, duration: 400, delay: 100, easing: (t) => 1 - Math.pow(1 - t, 3) }}>
                About <span class="text-primary dark:text-primary-light">Integr8sCode</span>
            </h1>
            <p class="text-lg text-fg-muted dark:text-dark-fg-muted max-w-2xl mx-auto"
               in:fly={{y: 10, duration: 400, delay: 200, easing: (t) => 1 - Math.pow(1 - t, 3) }}>
                Understanding the components and features that power your online Python execution environment.
            </p>
        </div>

        <!-- Features Grid -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6 lg:gap-8">
            {#each sections as section, i}
                <div class="card p-6 flex flex-col items-start text-left transform transition-all duration-300 hover:shadow-lg hover:-translate-y-1"
                     in:fly={{ y: 20, duration: 300, delay: 300 + i * 150, easing: (t) => 1 - Math.pow(1 - t, 3) }}>

                    {#if section.icon}
                    <div class="text-3xl mb-4 bg-primary/10 dark:bg-primary/20 text-primary dark:text-primary-light p-3 rounded-full">
                        <!-- Assuming icon is an emoji for now, adjust if it's SVG -->
                         {section.icon}
                    </div>
                    {/if}

                    <h2 class="text-xl font-semibold mb-2 text-fg-default dark:text-dark-fg-default">{section.title}</h2>
                    <p class="text-sm text-fg-muted dark:text-dark-fg-muted flex-grow">{section.content}</p>
                </div>
            {/each}
        </div>
    </div>
</div>
{/if}
