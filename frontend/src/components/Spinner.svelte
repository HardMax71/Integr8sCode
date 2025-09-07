<script>
  export let size = 'medium';
  export let color = 'primary';
  export let className = '';
  
  const sizeClasses = {
    small: 'h-4 w-4',
    medium: 'h-6 w-6',
    large: 'h-8 w-8',
    xlarge: 'h-12 w-12'
  };
  
  const colorClasses = {
    primary: 'text-primary dark:text-primary-light',
    white: 'text-white',
    current: 'text-current',
    muted: 'text-gray-400 dark:text-gray-500'
  };
  
  $: sizeClass = sizeClasses[size] || sizeClasses.medium;
  $: colorClass = colorClasses[color] || colorClasses.primary;
</script>

<svg 
  class="animate-spin {sizeClass} {colorClass} {className}" 
  xmlns="http://www.w3.org/2000/svg"
  fill="none" 
  viewBox="0 0 24 24"
  role="status" 
  aria-label="Loading"
>
  <circle 
    class="opacity-20" 
    cx="12" 
    cy="12" 
    r="10" 
    stroke="currentColor" 
    stroke-width="2"
  />
  <path 
    class="opacity-75" 
    fill="currentColor" 
    d="M12 2a10 10 0 00-10 10h2a8 8 0 018-8V2z"
  />
</svg>