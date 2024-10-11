<script>
  import { navigate } from "svelte-routing";
  import { addNotification } from "../stores/notifications.js";
  import { fade, fly } from "svelte/transition";
  import axios from "axios";

  let username = "";
  let email = "";
  let password = "";
  let confirmPassword = "";
  let loading = false;

  async function handleRegister() {
    if (password !== confirmPassword) {
      addNotification("Passwords do not match", "error");
      return;
    }

    loading = true;
    try {
      await axios.post("http://localhost:8000/api/v1/register", {
        username,
        email,
        password
      });

      addNotification("Registration successful. Please log in.", "success");
      navigate("/login");
    } catch (error) {
      addNotification(error.response?.data?.detail || "Registration failed", "error");
    } finally {
      loading = false;
    }
  }
</script>

<div class="min-h-screen flex items-center justify-center bg-gray-100" in:fade>
  <div class="bg-white p-8 rounded-lg shadow-md w-full max-w-md" in:fly={{ y: 20, duration: 300, delay: 200 }}>
    <h2 class="text-3xl font-bold mb-6 text-center text-gray-800">Register</h2>
    <form on:submit|preventDefault={handleRegister}>
      <div class="mb-4">
        <label class="block text-gray-700 text-sm font-bold mb-2" for="username">Username</label>
        <input class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" type="text" id="username" bind:value={username} required>
      </div>
      <div class="mb-4">
        <label class="block text-gray-700 text-sm font-bold mb-2" for="email">Email</label>
        <input class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" type="email" id="email" bind:value={email} required>
      </div>
      <div class="mb-4">
        <label class="block text-gray-700 text-sm font-bold mb-2" for="password">Password</label>
        <input class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" type="password" id="password" bind:value={password} required>
      </div>
      <div class="mb-6">
        <label class="block text-gray-700 text-sm font-bold mb-2" for="confirm-password">Confirm Password</label>
        <input class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" type="password" id="confirm-password" bind:value={confirmPassword} required>
      </div>
      <button class="w-full bg-blue-500 hover:bg-blue-600 text-white font-bold py-2 px-4 rounded-md focus:outline-none focus:shadow-outline" type="submit" disabled={loading}>
        {loading ? 'Registering...' : 'Register'}
      </button>
    </form>
  </div>
</div>