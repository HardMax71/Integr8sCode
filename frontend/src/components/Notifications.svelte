<script>
  import { notifications, removeNotification } from "../stores/notifications.js";
  import { fly } from "svelte/transition";
</script>

<div class="fixed top-4 right-4 z-50 max-w-sm">
  {#each $notifications as notification (notification.id)}
    <div
      class={`mb-2 p-4 rounded-md shadow-md ${notification.type === 'error' ? 'bg-red-500' : 'bg-green-500'} text-white`}
      in:fly={{ y: 50, duration: 300 }}
      out:fly={{ y: -50, duration: 300 }}
    >
      <button class="float-right font-bold" on:click={() => removeNotification(notification.id)}>×</button>
      <span>{notification.message}</span>
    </div>
  {/each}
</div>