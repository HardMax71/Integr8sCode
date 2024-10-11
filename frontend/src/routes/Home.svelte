<script>
  import { Link } from "svelte-routing";
  import { fade, fly } from "svelte/transition";
</script>

<div class="min-h-screen bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center" in:fade>
  <div class="text-center">
    <h1 class="text-5xl font-bold text-white mb-4" in:fly={{ y: -50, duration: 500 }}>Welcome to Integr8sCode</h1>
    <p class="text-2xl text-white mb-8" in:fly={{ y: 50, duration: 500, delay: 200 }}>Run Python scripts online with ease!</p>
    <Link to="/editor" class="bg-white text-blue-500 hover:bg-blue-100 font-bold py-2 px-4 rounded-full text-lg">Start Coding</Link>
  </div>
</div>