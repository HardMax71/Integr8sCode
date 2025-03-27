<div role="status" aria-label="Loading">
  <div class="spinner"></div>
</div>

<style>
  .spinner {
    width: 2rem; /* 32px */
    height: 2rem; /* 32px */
    border: 3px solid theme('colors.neutral.200');
    border-top-color: theme('colors.primary.DEFAULT');
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin: 1rem auto; /* Center it */
  }

  .dark .spinner {
     border-color: theme('colors.neutral.700');
     border-top-color: theme('colors.primary.light');
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>