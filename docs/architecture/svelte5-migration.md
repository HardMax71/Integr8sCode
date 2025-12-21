# Svelte 5 migration

## Why Svelte 5

Svelte 5 introduces runes — a new reactivity system that replaces Svelte 4's implicit reactivity with explicit declarations.

| Svelte 4                                                            | Svelte 5                                                         |
|---------------------------------------------------------------------|------------------------------------------------------------------|
| `let count = 0` was implicitly reactive only at component top-level | `let count = $state(0)` is explicitly reactive anywhere          |
| Reactivity couldn't be refactored into external files               | Runes work in `.svelte.ts` files, enabling shared reactive logic |
| `$:` reactive statements mixed derivations and side effects         | `$derived` and `$effect` separate concerns                       |
| Slots for component composition                                     | Snippets provide more flexible composition                       |

The migration also updated the router from `svelte-routing` to `@mateothegreat/svelte5-router`, which is designed for Svelte 5's component model.

## Runes overview

Runes are compiler directives that look like function calls but are processed at compile time. They're available in `.svelte` files and `.svelte.ts` files without imports.

### $state

Creates reactive state that triggers UI updates when modified:

```svelte
<script lang="ts">
  let count = $state(0);                         // Reactive primitive
  let user = $state({ name: '', email: '' });    // Reactive object (deeply reactive)
  let items = $state<Item[]>([]);                // Reactive array (.push() works)

  function increment() {
    count += 1;  // Triggers update
  }
</script>

<button onclick={increment}>{count}</button>
```

Use `$state` for variables displayed in the template that can change, variables controlling conditional rendering, arrays and objects that will be mutated, and any state that should trigger re-renders. Don't use `$state` for DOM element references (`bind:this`), cleanup functions and subscriptions, constants that never change, or helper variables used only inside functions:

```svelte
<script lang="ts">
  let loading = $state(false);           // Needs $state - displayed and updated
  let items = $state<Item[]>([]);        // Needs $state - displayed and mutated

  let containerEl: HTMLElement;          // No $state - DOM reference
  let unsubscribe: (() => void) | null;  // No $state - cleanup function
  const API_ENDPOINT = '/api/v1';        // No $state - constant
</script>
```

### $derived

Creates computed values that automatically update when dependencies change:

```svelte
<script lang="ts">
  let items = $state<Item[]>([]);
  let filter = $state('');

  let count = $derived(items.length);    // Simple derivation

  // Complex derivation with $derived.by
  let filteredItems = $derived.by(() => {
    if (!filter) return items;
    return items.filter(item =>
      item.name.toLowerCase().includes(filter.toLowerCase())
    );
  });
</script>
```

Use `$derived` for any value computed from reactive state. Use `$derived.by` when the computation needs multiple statements.

### $effect

Runs side effects when dependencies change:

```svelte
<script lang="ts">
  let theme = $state('dark');

  $effect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    return () => console.log('Cleaning up previous effect');  // Optional cleanup
  });
</script>
```

Use `$effect` sparingly — most reactive needs are better served by `$derived`. Reserve effects for DOM manipulation outside Svelte's control, external library integration, subscriptions and event listeners, and logging/debugging.

### $props

Declares component props with destructuring:

```svelte
<script lang="ts">
  // Svelte 4: export let size = 'medium';
  // Svelte 5:
  let { size = 'medium', disabled = false } = $props();

  // With TypeScript interface
  interface Props {
    size?: 'small' | 'medium' | 'large';
    disabled?: boolean;
    children?: Snippet;
  }
  let { size = 'medium', disabled = false, children } = $props<Props>();
</script>
```

## Event handlers

Svelte 5 uses standard DOM event attributes instead of the `on:` directive:

```svelte
<!-- Svelte 4 -->
<button on:click={handleClick}>Click</button>
<form on:submit|preventDefault={handleSubmit}>

<!-- Svelte 5 -->
<button onclick={handleClick}>Click</button>
<form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
```

| Svelte 4                    | Svelte 5                                                              |
|-----------------------------|-----------------------------------------------------------------------|
| `on:click\|preventDefault`  | `onclick={(e) => { e.preventDefault(); handler(); }}`                 |
| `on:click\|stopPropagation` | `onclick={(e) => { e.stopPropagation(); handler(); }}`                |
| `on:keydown\|self`          | `onkeydown={(e) => { if (e.target === e.currentTarget) handler(); }}` |

All standard DOM events follow this pattern: `on:eventname` becomes `oneventname`.

## Snippets

Snippets replace slots for component composition:

```svelte
<!-- Svelte 4: Parent -->
<Card>
  <h2 slot="header">Title</h2>
  <p>Content goes here</p>
</Card>

<!-- Svelte 4: Card.svelte -->
<div class="card">
  <slot name="header" />
  <slot />
</div>
```

```svelte
<!-- Svelte 5: Parent -->
<Card>
  {#snippet header()}
    <h2>Title</h2>
  {/snippet}
  <p>Content goes here</p>
</Card>

<!-- Svelte 5: Card.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    header?: Snippet;
    children?: Snippet;
  }
  let { header, children } = $props<Props>();
</script>

<div class="card">
  {#if header}{@render header()}{/if}
  {@render children?.()}
</div>
```

For simple cases with just a default slot, declare `children` as a `Snippet` prop and render with `{@render children?.()}`.

## Component instantiation

The `new Component()` syntax is replaced with `mount()`:

```typescript
// Svelte 4
const app = new App({ target: document.body });

// Svelte 5
import { mount } from 'svelte';
const app = mount(App, { target: document.body });
```

## Router migration

The frontend uses `@mateothegreat/svelte5-router` instead of `svelte-routing`. The main API change is that `navigate('/path')` becomes `goto('/path')`, and `<Link to="/path">` becomes `<a href="/path" use:route>`. The `<Route>` component syntax remains the same.

| svelte-routing                        | svelte5-router                        |
|---------------------------------------|---------------------------------------|
| `navigate('/path')`                   | `goto('/path')`                       |
| `<Link to="/path">`                   | `<a href="/path" use:route>`          |
| `<Route path="/" component={Home} />` | `<Route path="/" component={Home} />` |

Routes are configured in `App.svelte` by importing `Router` and `Route` from `@mateothegreat/svelte5-router`, then wrapping route definitions. Protected routes wrap their children in `ProtectedRoute`. For programmatic navigation, import `goto` from the router and call it after state changes like logout. For links, use the `route` action on anchor elements: `<a href="/settings" use:route>`.

## Stores compatibility

Svelte stores (`writable`, `derived`, `readable`) work unchanged in Svelte 5. The `$store` auto-subscription syntax continues to work:

```svelte
<script lang="ts">
  import { theme } from '../stores/theme';
  import { isAuthenticated, username } from '../stores/auth';
</script>

{#if $isAuthenticated}
  <span>Welcome, {$username}</span>
{/if}

<button onclick={() => theme.set('dark')}>Current: {$theme}</button>
```

Use stores for shared state across components, persisted state, and complex async state. Use runes (`$state`) for component-local state and simple reactive values. The existing stores (`auth.ts`, `theme.ts`, `toastStore.ts`) remain as stores because they manage global, shared state.

## Build configuration

The Svelte plugin in `rollup.config.js` requires the `runes: true` compiler option to enable Svelte 5's runes mode:

```javascript
svelte({
    preprocess: sveltePreprocess({ postcss: true }),
    compilerOptions: {
        dev: !production,
        runes: true,
    },
}),
```

The key dependencies are `svelte` at `^5.46.0`, `@mateothegreat/svelte5-router` at `^2.16.19`, and `svelte-preprocess` at `^6.0.3`.

## Migration patterns

The most common migration is converting reactive variables. A Svelte 4 variable `let count = 0` with a reactive statement `$: doubled = count * 2` becomes `let count = $state(0)` with `let doubled = $derived(count * 2)`.

For reactive statements with side effects, replace `$: if (query) { fetchResults(query); }` with an `$effect` block that runs the same logic. The effect automatically tracks `query` as a dependency.

Form handling changes in two ways: state variables get `$state`, and the form element uses `onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}` instead of `on:submit|preventDefault={handleSubmit}`.

Component props migrate from `export let size = 'medium'` to destructuring with `$props()`. If you need computed values from props, add a `$derived` declaration.

For cleanup patterns, both approaches work: the traditional `onMount`/`onDestroy` with an unsubscribe function, or the newer `$effect` with a cleanup return function. Choose whichever reads more clearly for your use case.

## Common pitfalls

Destructuring reactive objects breaks reactivity. If you have `let user = $state({ name: 'Alice' })`, don't destructure with `let { name } = user` — access properties directly as `user.name` in the template.

Variables that are reassigned and displayed in the template need `$state`. A plain `let count = 0` won't update the UI when incremented; it needs to be `let count = $state(0)`.

Avoid using `$effect` for derivations. If you find yourself writing `$effect(() => { total = items.reduce(...) })`, refactor to `let total = $derived(items.reduce(...))`. Effects are for side effects, not computed values.

HTML elements like `<textarea>`, `<div>`, and `<span>` cannot be self-closing in Svelte 5. Use `<textarea></textarea>` instead of `<textarea />`.

## File-by-file changes

| File                    | Changes                                |
|-------------------------|----------------------------------------|
| `main.ts`               | `new App()` → `mount(App, { target })` |
| `App.svelte`            | Router imports, `$derived` for theme   |
| `ProtectedRoute.svelte` | `$props`, snippet children, `goto()`   |
| `AdminLayout.svelte`    | `$props`, snippet children             |

| File                        | State variables                                          |
|-----------------------------|----------------------------------------------------------|
| `Header.svelte`             | `isMenuActive`, `isMobile`, `showUserDropdown`           |
| `Editor.svelte`             | `executing`, `result`, `showLimits`, `showOptions`, etc. |
| `ToastContainer.svelte`     | `toastList`                                              |
| `NotificationCenter.svelte` | `showDropdown`, `loading`, `notifications`               |
| `Spinner.svelte`            | None (uses `$derived` for `sizeClass`)                   |

All components using `on:click`, `on:submit`, `on:change`, etc. were updated to `onclick`, `onsubmit`, `onchange`.

## Verification

After migration, verify the build succeeds with `npm run build`. Expected output shows only Svelte internal circular dependency notes (normal for Svelte 5). 

Test that all routes navigate correctly, authentication works, protected routes redirect properly, theme switching works, notifications display, toast messages appear, the editor loads and executes code, and admin pages function correctly.
