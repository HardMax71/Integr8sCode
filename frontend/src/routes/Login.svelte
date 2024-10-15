<script>
  import { navigate } from "svelte-routing";
  import { login } from "../stores/auth.js";
  import { addNotification } from "../stores/notifications.js";
  import { fade, fly } from "svelte/transition";

  let username = "";
  let password = "";
  let loading = false;

  async function handleLogin() {
    loading = true;
    try {
      await login(username, password);
      addNotification("Login successful", "success");
      navigate("/editor");
    } catch (error) {
      addNotification(error.message || "Login failed", "error");
    } finally {
      loading = false;
    }
  }
</script>

<div class="min-h-screen flex items-center justify-center bg-gray-100" in:fade>
  <div class="bg-white p-8 rounded-lg shadow-md w-full max-w-md" in:fly={{ y: 20, duration: 300, delay: 200 }}>
    <h2 class="text-3xl font-bold mb-6 text-center text-gray-800">Login</h2>
    <form on:submit|preventDefault={handleLogin}>
      <div class="mb-4">
        <label class="block text-gray-700 text-sm font-bold mb-2" for="username">Username</label>
        <input class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" type="text" id="username" bind:value={username} required>
      </div>
      <div class="mb-6">
        <label class="block text-gray-700 text-sm font-bold mb-2" for="password">Password</label>
        <input class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" type="password" id="password" bind:value={password} required>
      </div>
      <button class="w-full bg-blue-500 hover:bg-blue-600 text-white font-bold py-2 px-4 rounded-md focus:outline-none focus:shadow-outline" type="submit" disabled={loading}>
        {loading ? 'Logging in...' : 'Login'}
      </button>
    </form>
  </div>
</div>