<script>
  import { Link } from "svelte-routing";
  import { fade, fly } from "svelte/transition";

  const features = [
    { icon: '🚀', title: "Instant Execution", content: "Run Python scripts online effortlessly in isolated Kubernetes pods." },
    { icon: '🛡️', title: "Secure & Efficient", content: "Strict resource limits and network restrictions ensure safe code execution." },
    { icon: '🔄', title: "Real-time Updates", content: "Get immediate feedback with real-time execution status and results." }
  ];
</script>

<div class="min-h-screen bg-gradient-to-br from-blue-500 to-purple-600 flex flex-col items-center justify-center p-4" in:fade>
  <div class="text-center mb-12">
    <h1 class="text-5xl font-bold text-white mb-4" in:fly={{ y: -50, duration: 500 }}>Welcome to Integr8sCode</h1>
    <p class="text-2xl text-white mb-8" in:fly={{ y: 50, duration: 500, delay: 200 }}>Run Python scripts online with ease!</p>
    <Link to="/editor" class="bg-white text-blue-500 hover:bg-blue-100 font-bold py-2 px-4 rounded-full text-lg transition duration-300">Start Coding</Link>
  </div>

  <div class="grid grid-cols-1 md:grid-cols-3 gap-6 max-w-4xl">
    {#each features as feature, i}
      <div class="bg-white bg-opacity-90 rounded-lg p-6 shadow-lg" in:fly={{ y: 20, duration: 300, delay: i * 100 }}>
        <div class="text-4xl mb-4">{feature.icon}</div>
        <h2 class="text-xl font-semibold mb-2 text-gray-800">{feature.title}</h2>
        <p class="text-gray-600">{feature.content}</p>
      </div>
    {/each}
  </div>
</div>