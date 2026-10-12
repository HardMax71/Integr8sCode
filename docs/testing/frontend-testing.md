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

Stores are Svelte 5 rune classes in `*.svelte.ts` files (auth.svelte.ts and theme.svelte.ts), so tests import the store instance and read its fields directly. To get a fresh instance, call `vi.resetModules()` and import the module again. The auth store's tests do that, so they also import `ApiError` and the query client after the reset: a class from before the reset isn't the one the fresh store checks with `instanceof`.

Shared helpers live in `src/__tests__/test-utils.ts`, imported as `#test/test-utils.ts`. The most used are `mockApi(fn).ok(data)` and `.err(error)` for the generated API functions (fixtures give timestamps as ISO strings, the way the API sends them), and `user`, a preconfigured `@testing-library/user-event` instance that test-utils exports. Like the real client, `.err()` rejects when the call passes `throwOnError`, which the generated query and mutation options always do.

A component that runs queries needs the query client from context, so render it with `renderWithQueryClient(Component, props)` instead of `render`. The admin stores and the editor's execution state build their queries when they're created, so their tests create them with `createInQueryContext(createSagasStore)`, which runs the factory inside a component under the provider and returns `{ value, unmount }`. Query results arrive asynchronously, so assert on them with `vi.waitFor` or `waitFor`. The generated functions pass extra options such as `signal` and `throwOnError`, so check SDK calls with `expect.objectContaining`. To test a branch on a status, such as the editor's 404 fallback, reject with an `ApiError`, since `.err()` rejects with the plain body.

Dialogs, menus, popovers and selects come from bits-ui and render their content in a portal at the end of `document.body`, outside the container `render` returns. Query them through `screen`, which searches the whole body. bits-ui decides whether a click landed outside by comparing its coordinates with the content's box, and happy-dom lays nothing out, so a click outside can't be simulated; the Playwright suite covers it. Escape, focus and keyboard navigation work in happy-dom.

Forms run on superforms, which submits asynchronously, so assert their results with `waitFor`, and check a field's error with `toHaveAccessibleDescription`, since formsnap ties it to the input through `aria-describedby`. superforms also finishes a submit a moment after it shows the errors and writes the submitted values back, so wait for the errors before typing again. The setup mocks the `beforeNavigate`, `afterNavigate` and `invalidateAll` it imports. Forms say `method="post"` in lowercase: SvelteKit's `enhance` compares `form.method` with `"post"`, and happy-dom returns the attribute as written.

E2E specs live in `frontend/e2e/`, not under `src/`.

## Configuration

```typescript
--8<-- "frontend/vitest.config.ts:config"
```

Coverage excludes the generated client in `src/lib/api/` and fails below the thresholds above.

[vitest.setup.ts](https://github.com/HardMax71/Integr8sCode/blob/main/frontend/vitest.setup.ts) runs before every test file and sets up global mocks, so most tests don't mock these themselves:

- fake timers with `shouldAdvanceTime: true`
- `#lib/api/sdk.gen.ts` with every generated API function replaced by a `vi.fn()`, while enums, Zod schemas, the client and the TanStack options stay real; mocking sdk.gen rather than the index means the generated query options, which import it directly, call the mocks too. A test that overrides `#lib/api/index.ts` spreads `importOriginal()` into its factory so the rest stays available
- `#lib/api-interceptors.ts` with a no-op `initializeApiInterceptors`, so no test gets the toast handler unless it sets one; `getErrorMessage` and `showApiError` stay real
- `svelte-sonner`'s `toast` and `goto` from `$app/navigation`; a test that needs `page` from `$app/state` mocks it in its own file
- `localStorage`, `sessionStorage` and `matchMedia`, plus `ResizeObserver` and `IntersectionObserver` as classes, since floating-ui (behind the bits-ui menus and popovers) constructs them with `new`
- `Element.prototype.animate`, which Svelte transitions call
- a `:checked` polyfill for `<select>`, since happy-dom lacks it and `bind:value` depends on it
- storage cleared, `cleanup()` run and the query cache cleared before each test

## Writing a test

```typescript
import { beforeEach, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { mockApi } from '#test/test-utils.ts';
import { registerApiV1AuthRegisterPost } from '#lib/api/index.ts';
import Register from '#routes/register/+page.svelte';

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
