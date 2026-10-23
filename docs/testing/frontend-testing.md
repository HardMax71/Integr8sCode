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

Unit tests sit in `__tests__/` directories next to the code they cover, under `src/`: `components/`, `routes/` and `routes/admin/`, `lib/` and its `admin/`, `editor/` and `notifications/` subfolders, and `utils/`. Vitest picks up `src/**/*.{test,spec}.{js,ts}`.

Who is signed in comes from `page.data.user`. The setup mocks `$app/state` with the stand-in in `#test/page.svelte.ts`, signed out on `https://localhost/` before every test, so a test signs in with `page.data.user = fakeUserResponse()` and sets `page.url` for the page it renders. The stand-in is `$state`, so a component rerenders when a test changes it. A layout component gets its user through the `data` prop instead, as SvelteKit passes it. The guards are plain `load` functions, tested by calling them with a `parent` that resolves to the user (`src/routes/__tests__/route-files.test.ts`).

Theme tests use mode-watcher as it is, with no mock: `setMode()` before rendering, then `userPrefersMode.current` or `mode.current`.

Shared helpers live in `src/__tests__/test-utils.ts`, imported as `#test/test-utils.ts`. The most used are `mockApi(fn).ok(data)` and `.err(error)` for the generated API functions, where `data` is typed from the function's generated return type, `mockStreamEvents(fn, ...events)` for the SSE functions, and `user`, a preconfigured `@testing-library/user-event` instance that test-utils exports. Like the real client, `.err()` rejects when the call passes `throwOnError`, which the generated query and mutation options always do.

Fixtures come from the Faker factories that hey-api generates into `src/lib/api/@faker-js/faker.gen.ts`, one `fakeX()` per schema in the spec, so they follow its enums, ranges and defaults. A test spreads the values it depends on over a fake, such as `{ ...fakeUserResponse(), username: 'alice', is_active: false }`. The setup seeds faker before every test and fixes its reference date, so a fake comes out the same on every run. Its values still shift when the spec changes, so a test sets every field it asserts on or that picks the branch it tests, or it asserts against the fake's own value.

Mocks sit at the generated SDK functions, not at the network, so hey-api's MSW plugin isn't used. Generated code builds the requests MSW would catch, and the Playwright suite sends the real ones to the real backend.

A component that runs queries needs the query client from context, so render it with `renderWithQueryClient(Component, props)` instead of `render`. The editor's execution state builds its mutation when it's created, so its test creates it with `createInQueryContext(createExecutionState)`, which runs the factory inside a component under the provider and returns `{ value, unmount }`. Query results arrive asynchronously, so assert on them with `vi.waitFor` or `waitFor`. The generated functions pass extra options such as `signal` and `throwOnError`, so check SDK calls with `expect.objectContaining`. `.err()` takes an `ErrorResponse`, so a test gives it the status it's about, such as the 404 behind the editor's create-instead-of-update fallback. The query client retries status 0 and 5xx, so a test of a failed load that shouldn't wait for retries uses a 4xx.

Dialogs, menus, popovers and selects come from bits-ui and render their content in a portal at the end of `document.body`, outside the container `render` returns. Query them through `screen`, which searches the whole body. bits-ui decides whether a click landed outside by comparing its coordinates with the content's box, and happy-dom lays nothing out, so a click outside can't be simulated; the Playwright suite covers it. Escape, focus and keyboard navigation work in happy-dom.

Forms run on superforms, which submits asynchronously, so assert their results with `waitFor`, and check a field's error with `toHaveAccessibleDescription`, since formsnap ties it to the input through `aria-describedby`. superforms also finishes a submit a moment after it shows the errors and writes the submitted values back, so wait for the errors before typing again. The setup mocks the `beforeNavigate`, `afterNavigate` and `refreshAll` it imports. Forms say `method="post"` in lowercase: SvelteKit's `enhance` compares `form.method` with `"post"`, and happy-dom returns the attribute as written.

E2E specs live in `frontend/e2e/`, not under `src/`.

## Configuration

```typescript
--8<-- "frontend/vitest.config.ts:config"
```

Coverage excludes the generated client in `src/lib/api/` and fails below the thresholds above. Before each test the config resets every mock to the implementation it was created with, restores spies and undoes `vi.stubGlobal`, and the run's time zone is pinned to UTC, so a test sets up only what it needs and cleans up nothing.

[vitest.setup.ts](https://github.com/HardMax71/Integr8sCode/blob/main/frontend/vitest.setup.ts) runs before every test file and sets up global mocks, so most tests don't mock these themselves:

- a fresh fake clock for each test, with `shouldAdvanceTime: true`, so a test can set the time or the tick mode without putting it back
- `#lib/api/sdk.gen.ts` with every generated API function replaced by a `vi.fn()`, while enums, Zod schemas, the client and the TanStack options stay real; mocking sdk.gen rather than the index means the generated query options, which import it directly, call the mocks too. A test that overrides `#lib/api/index.ts` spreads `importOriginal()` into its factory so the rest stays available
- `#lib/api-interceptors.ts` with a no-op `initializeApiInterceptors`, so no test gets the toast handler unless it sets one; `showApiError` stays real
- `svelte-sonner`'s `toast`, `goto` from `$app/navigation`, and `match` from `$app/paths`, which needs the router of a started app; a test sets the route it returns with `vi.mocked(match).mockResolvedValue(...)`, and `resolve` stays real. `page` from `$app/state`, replaced by the stand-in above while the module's other exports stay real
- `matchMedia`, plus `ResizeObserver` and `IntersectionObserver` as one no-op class, since floating-ui (behind the bits-ui menus and popovers) constructs them with `new`; the setup stubs them in its `beforeEach`, after the config has undone the last test's stubs
- `Element.prototype.animate`, which Svelte transitions call
- a `:checked` polyfill for `<select>`, since happy-dom lacks it and `bind:value` depends on it
- `localStorage` cleared, the `page` stand-in reset, the query cache cleared and faker seeded before each test; Testing Library unmounts what a test rendered by itself

## Writing a test

```typescript
import { beforeEach, expect, it } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { mockApi } from '#test/test-utils.ts';
import { registerApiV1AuthRegisterPost } from '#lib/api/index.ts';
import { fakeUserResponse } from '#lib/api/@faker-js/faker.gen.ts';
import Register from '#routes/register/+page.svelte';

beforeEach(() => {
    mockApi(registerApiV1AuthRegisterPost).ok(fakeUserResponse());
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

The suite runs against the stack on `https://localhost:5001`, which is the compose frontend that `docker compose up -d` starts. `npm run dev` can't stand in for it, since its proxy sends `/api` to a hostname that only resolves inside the compose network. The only account the suite expects is the seeded admin, whose password it reads from `ADMIN_USER_PASSWORD` like seed_users.py does, falling back to `admin123`.

[`e2e/fixtures.ts`](https://github.com/HardMax71/Integr8sCode/blob/main/frontend/e2e/fixtures.ts) registers one account per worker through the API and signs it and the seeded admin in once per worker, so two workers never share a user's settings, scripts or notifications. Every test gets a fresh browser context: `page` for a guest, and `userPage` or `adminPage` starting with the worker's session cookies, so nothing one test leaves in localStorage reaches the next. The `api` fixture is an API client signed in as the worker's user, and `execution` starts an execution through it for the tests that need one, such as the notification and admin table tests.

Tests don't sleep or write polling loops. They assert on what the page shows with Playwright's retrying assertions, and hold a request with `page.route` to look at a loading state. Labels come from `fieldTitle` and option lists from the generated enums and schemas, the same sources the pages use. svelte-check and Prettier cover `e2e/` as well. In CI a failed test is retried once to record a second trace, and a test that passes only on the retry still fails the run. Every page also collects JS coverage for the monocart reporter, which writes `coverage/e2e/`.

## In CI

CI runs `npm run test:coverage` in its frontend unit job and uploads the lcov report to Codecov. The same workflow runs the Playwright suite in two shards against the freshly built images. Frontend CI runs ESLint, Stylelint, Prettier, `svelte-check` and the production build, but no tests. See [CI/CD](../operations/cicd.md#e2e).
