# Frontend testing

Unit and component tests run on [Vitest](https://vitest.dev/) 5 with [happy-dom](https://github.com/capricorn86/happy-dom) and `@testing-library/svelte`. End-to-end tests run on [Playwright](https://playwright.dev/) in Chromium against the real stack.

```bash
cd frontend
npm run test             # vitest run
npm run test:watch       # watch mode
npm run test:coverage    # with v8 coverage and thresholds
npm run test:e2e         # playwright, needs the stack on https://localhost:5001
```

## Layout

Unit tests sit in `__tests__/` directories next to the code they cover, under `src/`: `components/`, `routes/` and `routes/admin/`, `stores/`, `lib/` and its `admin/`, `editor/` and `notifications/` subfolders, and `utils/`. Vitest picks up `src/**/*.{test,spec}.{js,ts}`.

Stores are Svelte 5 rune classes in `*.svelte.ts` files (auth.svelte.ts, theme.svelte.ts, errorStore.svelte.ts, notificationStore.svelte.ts, userSettings.svelte.ts), so tests import the store instance and read its fields directly. To get a fresh instance, call `vi.resetModules()` and import the module again.

Shared helpers live in `src/__tests__/test-utils.ts`, imported as `$test/test-utils`. The most used are `mockApi(fn).ok(data)` and `.err(error)` for the generated API functions, and a preconfigured `user` from `@testing-library/user-event`.

E2E specs live in `frontend/e2e/`, not under `src/`.

## Configuration

```typescript
--8<-- "frontend/vitest.config.ts:config"
```

Coverage excludes the generated client in `src/lib/api/` and fails below the thresholds above.

[vitest.setup.ts](https://github.com/HardMax71/Integr8sCode/blob/main/frontend/vitest.setup.ts) runs before every test file and sets up global mocks, so most tests don't mock these themselves:

- fake timers with `shouldAdvanceTime: true`
- `$lib/api` automocked, so every generated API function is a `vi.fn()`
- `$lib/api-interceptors` with simple `unwrap` and `unwrapOr` that throw or fall back the way the real ones do
- `svelte-sonner`'s `toast` and the router's `goto` and `route`
- `localStorage`, `sessionStorage`, `matchMedia`, `ResizeObserver` and `IntersectionObserver`
- `Element.prototype.animate`, which Svelte transitions call
- a `:checked` polyfill for `<select>`, since happy-dom lacks it and `bind:value` depends on it
- storage cleared and `cleanup()` run before each test

## Writing a test

```typescript
import { beforeEach, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { mockApi } from '$test/test-utils';
import { registerApiV1AuthRegisterPost } from '$lib/api';
import Register from '$routes/Register.svelte';

beforeEach(() => {
    vi.clearAllMocks();
    mockApi(registerApiV1AuthRegisterPost).ok({});
});

it('shows the form', async () => {
    render(Register);
    expect(screen.getByRole('button', { name: /create account/i })).toBeInTheDocument();
});
```

When a `vi.mock` factory refers to mock functions, create them in `vi.hoisted()`. `vi.mock` is hoisted above the imports, so ordinary top-level variables don't exist yet when the factory runs.

## E2E

```typescript
--8<-- "frontend/playwright.config.ts:config"
```

Outside CI, Playwright starts `npm run dev` on `https://localhost:5001` unless something already listens there, such as the compose frontend. The suites need a backend with seeded users either way.

[`e2e/fixtures.ts`](https://github.com/HardMax71/Integr8sCode/blob/main/frontend/e2e/fixtures.ts) logs in once per worker. The worker-scoped `userContext` and `adminContext` hold the logged-in browser contexts, and each test gets a fresh `userPage` or `adminPage` from them. Tests of the login flow itself use the plain `page` and `clearSession()`. Every page also collects JS coverage for the monocart reporter, which writes `coverage/e2e/`.

## In CI

Stack Tests runs `npm run test:coverage` in its frontend unit job and uploads the lcov report to Codecov. The same workflow runs the Playwright suite in two shards against the freshly built images. Frontend CI runs ESLint, Stylelint, Prettier, `svelte-check` and the production build, but no tests. See [CI/CD](../operations/cicd.md#stack-tests).
