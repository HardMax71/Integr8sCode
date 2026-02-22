declare module 'svelte/internal/client' {
  export function effect_root(fn: () => void): () => void;
}
