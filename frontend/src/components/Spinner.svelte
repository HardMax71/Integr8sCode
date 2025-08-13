<script>
  export let size = 'medium';
  
  $: sizeClass = {
    small: 'spinner-small',
    medium: 'spinner-medium', 
    large: 'spinner-large'
  }[size] || 'spinner-medium';
</script>

<div role="status" aria-label="Loading">
  <div class="spinner {sizeClass}"></div>
</div>

<style>
  .spinner {
    border: 3px solid theme('colors.neutral.200');
    border-top-color: theme('colors.primary.DEFAULT');
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin: 1rem auto; /* Center it */
  }
  
  .spinner-small {
    width: 1.5rem; /* 24px */
    height: 1.5rem; /* 24px */
    border-width: 2px;
  }
  
  .spinner-medium {
    width: 2rem; /* 32px */
    height: 2rem; /* 32px */
  }
  
  .spinner-large {
    width: 3rem; /* 48px */
    height: 3rem; /* 48px */
    border-width: 4px;
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