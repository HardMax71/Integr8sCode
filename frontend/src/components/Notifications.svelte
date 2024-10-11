<script>
  import { notifications, removeNotification } from "../stores/notifications.js";
  import { fly } from "svelte/transition";
</script>

<div class="fixed top-6 right-6 z-50 max-w-sm space-y-4">
  {#each $notifications as notification (notification.id)}
    <div
      class={`p-4 rounded-md shadow-lg ${
        notification.type === 'error' ? 'bg-red-500' : 'bg-green-500'
      } text-white relative flex items-center`}
      in:fly={{ y: 50, duration: 300 }}
      out:fly={{ y: -50, duration: 300 }}
    >
      <div class="flex-grow pr-8">
        <span class="block">{notification.message}</span>
      </div>
      <button
        class="absolute top-2 right-2 w-6 h-6 flex items-center justify-center text-white opacity-70 hover:opacity-100 transition-opacity duration-200"
        on:click={() => removeNotification(notification.id)}
        aria-label="Close notification"
      >
        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
        </svg>
      </button>
    </div>
  {/each}
</div>