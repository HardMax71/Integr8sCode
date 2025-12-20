# Svelte 5 migration

This document explains the migration from Svelte 4 to Svelte 5, covering the new runes API, reactivity model, and
practical patterns used throughout the frontend. It serves as both a reference for understanding the current codebase
and a guide for future development.

## Why Svelte 5

Svelte 5 introduces **runes** — a new reactivity system that replaces Svelte 4's implicit reactivity with explicit
declarations. The key benefits:

| Svelte 4                                                            | Svelte 5                                                         |
|---------------------------------------------------------------------|------------------------------------------------------------------|
| `let count = 0` was implicitly reactive only at component top-level | `let count = $state(0)` is explicitly reactive anywhere          |
| Reactivity couldn't be refactored into external files               | Runes work in `.svelte.ts` files, enabling shared reactive logic |
| `$:` reactive statements mixed derivations and side effects         | `$derived` and `$effect` separate concerns                       |
| Slots for component composition                                     | Snippets provide more flexible composition                       |

The migration also updated the router from `svelte-routing` to `@mateothegreat/svelte5-router`, which is designed for
Svelte 5's component model.

## Runes overview

Runes are compiler directives that look like function calls but are processed at compile time. They're available in
`.svelte` files and `.svelte.ts` files without imports.

### $state

Creates reactive state that triggers UI updates when modified:

```svelte
<script lang="ts">
  // Reactive primitive
  let count = $state(0);

  // Reactive object (deeply reactive)
  let user = $state({ name: '', email: '' });

  // Reactive array (deeply reactive, .push() works)
  let items = $state<Item[]>([]);

  function increment() {
    count += 1;  // Triggers update
  }
</script>

<button onclick={increment}>{count}</button>
```

**When to use `$state`:**

- Variables displayed in the template that can change
- Variables controlling conditional rendering (`{#if loading}`)
- Arrays and objects that will be mutated
- Any state that should trigger re-renders

**When NOT to use `$state`:**

- DOM element references (`bind:this`)
- Cleanup functions and subscriptions
- Constants that never change
- Helper variables used only inside functions

```svelte
<script lang="ts">
  // ✅ Needs $state - displayed and updated
  let loading = $state(false);
  let items = $state<Item[]>([]);

  // ✅ Does NOT need $state - DOM reference
  let containerEl: HTMLElement;

  // ✅ Does NOT need $state - cleanup function
  let unsubscribe: (() => void) | null = null;

  // ✅ Does NOT need $state - constant
  const API_ENDPOINT = '/api/v1';
</script>
```

### $derived

Creates computed values that automatically update when dependencies change:

```svelte
<script lang="ts">
  let items = $state<Item[]>([]);
  let filter = $state('');

  // Simple derivation
  let count = $derived(items.length);

  // Complex derivation with $derived.by
  let filteredItems = $derived.by(() => {
    if (!filter) return items;
    return items.filter(item =>
      item.name.toLowerCase().includes(filter.toLowerCase())
    );
  });
</script>
```

Use `$derived` for any value computed from reactive state. Use `$derived.by` when the computation needs multiple
statements.

### $effect

Runs side effects when dependencies change:

```svelte
<script lang="ts">
  let theme = $state('dark');

  $effect(() => {
    // Runs when theme changes
    document.documentElement.classList.toggle('dark', theme === 'dark');

    // Optional cleanup function
    return () => {
      console.log('Cleaning up previous effect');
    };
  });
</script>
```

!!! warning "Use $effect sparingly"
Most reactive needs are better served by `$derived`. Use `$effect` only for:

    - DOM manipulation outside Svelte's control
    - External library integration
    - Subscriptions and event listeners
    - Logging and debugging

### $props

Declares component props with destructuring:

```svelte
<script lang="ts">
  // Svelte 4
  export let size = 'medium';
  export let disabled = false;

  // Svelte 5
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
<button on:click|preventDefault={submit}>Submit</button>
<form on:submit|preventDefault={handleSubmit}>

<!-- Svelte 5 -->
<button onclick={handleClick}>Click</button>
<button onclick={(e) => { e.preventDefault(); submit(); }}>Submit</button>
<form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
```

### Event modifier migration

| Svelte 4                    | Svelte 5                                                              |
|-----------------------------|-----------------------------------------------------------------------|
| `on:click\|preventDefault`  | `onclick={(e) => { e.preventDefault(); handler(); }}`                 |
| `on:click\|stopPropagation` | `onclick={(e) => { e.stopPropagation(); handler(); }}`                |
| `on:keydown\|self`          | `onkeydown={(e) => { if (e.target === e.currentTarget) handler(); }}` |

All standard DOM events follow this pattern: `on:eventname` becomes `oneventname`.

## Snippets (replacing slots)

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
  {#if header}
    {@render header()}
  {/if}
  {@render children?.()}
</div>
```

For simple cases with just a default slot:

```svelte
<!-- ProtectedRoute.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    children?: Snippet;
    redirectTo?: string;
  }
  let { children, redirectTo = '/login' } = $props<Props>();
</script>

{#if authenticated}
  {@render children?.()}
{/if}
```

## Component instantiation

The `new Component()` syntax is replaced with `mount()`:

```typescript
// Svelte 4: main.ts
import App from './App.svelte';

const app = new App({
    target: document.body,
});

// Svelte 5: main.ts
import {mount} from 'svelte';
import App from './App.svelte';

const app = mount(App, {
    target: document.body,
});
```

## Router migration

The frontend uses `@mateothegreat/svelte5-router` instead of `svelte-routing`:

### API changes

| svelte-routing                        | svelte5-router                        |
|---------------------------------------|---------------------------------------|
| `navigate('/path')`                   | `goto('/path')`                       |
| `<Link to="/path">`                   | `<a href="/path" use:route>`          |
| `<Route path="/" component={Home} />` | `<Route path="/" component={Home} />` |

### Route configuration

```svelte
<!-- App.svelte -->
<script lang="ts">
  import { Router, Route } from "@mateothegreat/svelte5-router";
  import Home from "./routes/Home.svelte";
  import Login from "./routes/Login.svelte";
  import ProtectedRoute from "./components/ProtectedRoute.svelte";
  import Editor from "./routes/Editor.svelte";
</script>

<Router>
  <Route path="/" component={Home} />
  <Route path="/login" component={Login} />
  <Route path="/editor">
    <ProtectedRoute>
      <Editor />
    </ProtectedRoute>
  </Route>
</Router>
```

### Programmatic navigation

```svelte
<script lang="ts">
  import { goto } from "@mateothegreat/svelte5-router";

  function handleLogout() {
    // Clear auth state
    goto('/login');
  }
</script>
```

### Link styling with route action

```svelte
<script lang="ts">
  import { route } from "@mateothegreat/svelte5-router";
</script>

<a href="/settings" use:route class="nav-link">Settings</a>
<a href="/logout" use:route onclick={handleLogout}>Logout</a>
```

## Stores compatibility

Svelte stores (`writable`, `derived`, `readable`) work unchanged in Svelte 5. The `$store` auto-subscription syntax
continues to work:

```svelte
<script lang="ts">
  import { theme } from '../stores/theme';
  import { isAuthenticated, username } from '../stores/auth';
</script>

{#if $isAuthenticated}
  <span>Welcome, {$username}</span>
{/if}

<button onclick={() => theme.set('dark')}>
  Current: {$theme}
</button>
```

!!! note "When to use stores vs runes"
- **Stores**: Shared state across components, persisted state, complex async state
- **Runes ($state)**: Component-local state, simple reactive values

    The existing stores (`auth.ts`, `theme.ts`, `toastStore.ts`) remain as stores because they manage global, shared state.

## Build configuration

### rollup.config.js

The Svelte plugin requires the `runes: true` compiler option:

```javascript
import svelte from 'rollup-plugin-svelte';
import sveltePreprocess from 'svelte-preprocess';

export default {
    plugins: [
        svelte({
            preprocess: sveltePreprocess({postcss: true}),
            compilerOptions: {
                dev: !production,
                runes: true,  // Enable runes mode
            },
        }),
        // ... other plugins
    ],
};
```

### package.json dependencies

```json
{
  "dependencies": {
    "svelte": "^5.46.0",
    "@mateothegreat/svelte5-router": "^2.16.19"
  },
  "devDependencies": {
    "svelte-preprocess": "^6.0.3"
  }
}
```

## Migration patterns

### Pattern 1: Simple reactive variable

```svelte
<!-- Before -->
<script>
  let count = 0;
  $: doubled = count * 2;
</script>

<!-- After -->
<script lang="ts">
  let count = $state(0);
  let doubled = $derived(count * 2);
</script>
```

### Pattern 2: Reactive statement with side effect

```svelte
<!-- Before -->
<script>
  let query = '';
  $: if (query) {
    fetchResults(query);
  }
</script>

<!-- After -->
<script lang="ts">
  let query = $state('');

  $effect(() => {
    if (query) {
      fetchResults(query);
    }
  });
</script>
```

### Pattern 3: Form with loading state

```svelte
<!-- Before -->
<script>
  let loading = false;
  let error = null;

  async function handleSubmit() {
    loading = true;
    error = null;
    try {
      await submitForm();
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }
</script>

<form on:submit|preventDefault={handleSubmit}>

<!-- After -->
<script lang="ts">
  let loading = $state(false);
  let error = $state<string | null>(null);

  async function handleSubmit() {
    loading = true;
    error = null;
    try {
      await submitForm();
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }
</script>

<form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
```

### Pattern 4: Component with props and children

```svelte
<!-- Before: Spinner.svelte -->
<script>
  export let size = 'medium';
  export let className = '';
</script>

<!-- After: Spinner.svelte -->
<script lang="ts">
  interface Props {
    size?: 'small' | 'medium' | 'large';
    className?: string;
  }
  let { size = 'medium', className = '' } = $props<Props>();

  let sizeClass = $derived(
    size === 'small' ? 'w-4 h-4' :
    size === 'large' ? 'w-12 h-12' : 'w-8 h-8'
  );
</script>

<div class="{sizeClass} {className}">
  <!-- spinner SVG -->
</div>
```

### Pattern 5: Cleanup with subscriptions

```svelte
<!-- Before -->
<script>
  import { onDestroy } from 'svelte';
  import { someStore } from './stores';

  let unsubscribe;

  onMount(() => {
    unsubscribe = someStore.subscribe(value => {
      // handle value
    });
  });

  onDestroy(() => {
    if (unsubscribe) unsubscribe();
  });
</script>

<!-- After (both approaches work) -->
<script lang="ts">
  import { onDestroy } from 'svelte';
  import { someStore } from './stores';

  // Approach 1: Keep using onDestroy (still valid)
  let unsubscribe: (() => void) | null = null;

  onMount(() => {
    unsubscribe = someStore.subscribe(value => {
      // handle value
    });
  });

  onDestroy(() => {
    unsubscribe?.();
  });

  // Approach 2: Use $effect cleanup
  $effect(() => {
    const unsub = someStore.subscribe(value => {
      // handle value
    });
    return () => unsub();
  });
</script>
```

## Common pitfalls

### Destructuring reactive values

Destructuring breaks reactivity:

```svelte
<script lang="ts">
  let user = $state({ name: 'Alice', age: 30 });

  // ❌ Bad: loses reactivity
  let { name } = user;

  // ✅ Good: access properties directly
  // In template: {user.name}
</script>
```

### Missing $state on mutable variables

Variables that are reassigned AND displayed in the template need `$state`:

```svelte
<script lang="ts">
  // ❌ Bad: won't update UI when changed
  let count = 0;

  // ✅ Good: UI updates on change
  let count = $state(0);
</script>

<button onclick={() => count++}>{count}</button>
```

### Using $effect for derivations

```svelte
<script lang="ts">
  let items = $state<Item[]>([]);

  // ❌ Bad: using $effect for a derivation
  let total = $state(0);
  $effect(() => {
    total = items.reduce((sum, item) => sum + item.price, 0);
  });

  // ✅ Good: use $derived
  let total = $derived(
    items.reduce((sum, item) => sum + item.price, 0)
  );
</script>
```

### Self-closing non-void elements

HTML elements like `<textarea>`, `<div>`, `<span>` cannot be self-closing:

```svelte
<!-- ❌ Bad: causes parsing errors -->
<textarea />
<div />

<!-- ✅ Good: use closing tags -->
<textarea></textarea>
<div></div>
```

## File-by-file changes

### Critical files

| File                    | Changes                                |
|-------------------------|----------------------------------------|
| `main.ts`               | `new App()` → `mount(App, { target })` |
| `App.svelte`            | Router imports, `$derived` for theme   |
| `ProtectedRoute.svelte` | `$props`, snippet children, `goto()`   |
| `AdminLayout.svelte`    | `$props`, snippet children             |

### Components with $state

| File                        | State variables                                          |
|-----------------------------|----------------------------------------------------------|
| `Header.svelte`             | `isMenuActive`, `isMobile`, `showUserDropdown`           |
| `Editor.svelte`             | `executing`, `result`, `showLimits`, `showOptions`, etc. |
| `ToastContainer.svelte`     | `toastList`                                              |
| `NotificationCenter.svelte` | `showDropdown`, `loading`, `notifications`               |
| `Spinner.svelte`            | None (uses `$derived` for `sizeClass`)                   |

### Components with event syntax updates

All components using `on:click`, `on:submit`, `on:change`, etc. were updated to `onclick`, `onsubmit`, `onchange`. This
includes all form components, buttons, and interactive elements.

## Verification

After migration, verify the build succeeds without warnings:

```bash
cd frontend
npm run build
```

Expected output shows only Svelte internal circular dependency notes (normal for Svelte 5):

```
src/main.ts → public/build...
(!) Circular dependencies
node_modules/svelte/src/internal/...
...and 34 more
created public/build in 12.5s
```

Test the application:

- [ ] All routes navigate correctly
- [ ] Authentication flow works (login/logout)
- [ ] Protected routes redirect properly
- [ ] Theme switching works
- [ ] Notifications display and update
- [ ] Toast messages appear
- [ ] Editor loads and executes code
- [ ] Admin pages function correctly

## References

- [Svelte 5 Documentation](https://svelte.dev/docs/svelte)
- [Svelte 5 Migration Guide](https://svelte.dev/docs/svelte/v5-migration-guide)
- [$state Rune](https://svelte.dev/docs/svelte/$state)
- [$derived Rune](https://svelte.dev/docs/svelte/$derived)
- [$effect Rune](https://svelte.dev/docs/svelte/$effect)
- [svelte5-router](https://github.com/mateothegreat/svelte5-router)
