declare module 'svelte/internal/client' {
  export function effect_root(fn: () => void): () => void;
  export function proxy<T extends object>(value: T): T;
}
