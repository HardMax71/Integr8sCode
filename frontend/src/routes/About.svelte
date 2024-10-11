<script>
    import { fade, fly } from 'svelte/transition';
    import { onMount } from 'svelte';

    let visible = false;
    onMount(() => { visible = true; });

    const sections = [
        { icon: '🏗️', title: "Architecture", content: "Built with a Svelte frontend, FastAPI backend, and MongoDB database, all orchestrated with Kubernetes for robust performance." },
        { icon: '🔑', title: "Key Features", content: "User authentication, robust resource management, and isolated execution environments for enhanced security and efficiency." },
        { icon: '🔀', title: "Integrations", content: "Seamlessly integrated with Kubernetes for container orchestration and MongoDB for efficient data storage and retrieval." },
       ];
</script>

<div class="about-container" in:fade={{duration: 300}}>
    <h1 class="title">About Integr8sCode</h1>

    {#if visible}
        <div class="grid">
            {#each sections as { icon, title, content }, i}
                <div class="card" in:fly={{y: 20, duration: 300, delay: i * 100}}>
                    <div class="icon">{icon}</div>
                    <h2>{title}</h2>
                    <p>{content}</p>
                </div>
            {/each}
        </div>
    {/if}
</div>

<style>
    .about-container {
        max-width: 1200px;
        margin: 2rem auto;
        padding: 2rem;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 20px;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
    }

    .title {
        font-size: 3rem;
        color: #ffffff;
        text-align: center;
        margin-bottom: 2rem;
        text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
    }

    .grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
        gap: 1.5rem;
    }

    .card {
        background: rgba(255, 255, 255, 0.9);
        border-radius: 15px;
        padding: 1.5rem;
        transition: all 0.3s ease;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }

    .card:hover {
        transform: translateY(-5px);
        box-shadow: 0 10px 20px rgba(0, 0, 0, 0.2);
    }

    .icon {
        font-size: 2.5rem;
        margin-bottom: 1rem;
    }

    h2 {
        font-size: 1.5rem;
        color: #4a5568;
        margin-bottom: 0.5rem;
    }

    p {
        font-size: 1rem;
        color: #718096;
        line-height: 1.5;
    }

    @media (max-width: 768px) {
        .about-container {
            padding: 1.5rem;
            margin: 1rem;
        }

        .title {
            font-size: 2.5rem;
        }

        .grid {
            grid-template-columns: 1fr;
        }
    }
</style>