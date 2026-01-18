# Frontend testing

The frontend uses [Vitest](https://vitest.dev/) for unit and integration tests, with
[Playwright](https://playwright.dev/) for end-to-end scenarios. Tests live alongside the source code in `__tests__`
directories, following the same structure as the components they verify. The setup uses jsdom for DOM simulation and
@testing-library/svelte for component rendering.

## Quick start

Run all unit tests from the frontend directory:

```bash
cd frontend
npm run test
```

For continuous development with watch mode:

```bash
npm run test:watch
```

Run with coverage report:

```bash
npm run test:coverage
```

End-to-end tests require the full stack running locally:

```bash
npm run test:e2e
```

## Test structure

Tests follow a consistent directory layout that mirrors the source code. Each testable module has a `__tests__` folder next to it containing the corresponding test files:

```
src/
├── stores/
│   ├── auth.ts
│   ├── theme.ts
│   ├── toastStore.ts
│   ├── notificationStore.ts
│   ├── errorStore.ts
│   └── __tests__/
│       ├── auth.test.ts
│       ├── theme.test.ts
│       ├── toastStore.test.ts
│       ├── notificationStore.test.ts
│       └── errorStore.test.ts
├── lib/
│   ├── auth-init.ts
│   ├── settings-cache.ts
│   ├── user-settings.ts
│   └── __tests__/
│       ├── auth-init.test.ts
│       ├── settings-cache.test.ts
│       └── user-settings.test.ts
├── utils/
│   ├── meta.ts
│   └── __tests__/
│       └── meta.test.ts
├── components/
│   ├── Spinner.svelte
│   ├── ErrorDisplay.svelte
│   ├── Footer.svelte
│   ├── ToastContainer.svelte
│   └── __tests__/
│       ├── Spinner.test.ts
│       ├── ErrorDisplay.test.ts
│       ├── Footer.test.ts
│       └── ToastContainer.test.ts
└── e2e/
    ├── auth.spec.ts
    └── theme.spec.ts
```

## What gets tested

The test suite covers several layers of the application, from pure logic to rendered components.

Stores handle reactive state management. Tests verify initial values, state transitions, persistence to localStorage, and subscription behavior. The auth store tests, for example, check login/logout flows, token verification with caching, and graceful handling of network errors with offline-first fallbacks.

Library utilities deal with initialization, caching, and API interactions. The auth-init tests verify the startup sequence that restores persisted sessions, validates tokens with the backend, and handles edge cases like expired or corrupted localStorage data. Settings cache tests ensure proper TTL expiration and nested object updates.

Component tests render Svelte components in jsdom and verify their DOM output, props handling, and user interactions. The Spinner tests check that size and color props produce the expected CSS classes. ErrorDisplay tests verify that network errors show user-friendly messages without exposing raw error details. ToastContainer tests confirm that toasts appear, animate, and disappear on schedule.

E2E tests run in Playwright against the real application. They exercise full user flows like registration, login, theme switching, and protected route access.

## Playwright authentication

E2E tests use worker-scoped fixtures to authenticate once per worker and reuse the browser context across all tests. This avoids hammering the backend with 100+ login requests.

### How it works

1. **Worker-scoped fixtures** (`userContext`, `adminContext`) authenticate once when a worker starts
2. The authenticated browser context is kept alive for the entire worker lifetime
3. **Test-scoped fixtures** (`userPage`, `adminPage`) create new pages within the authenticated context

```text
e2e/
├── fixtures.ts         # Worker-scoped auth fixtures
├── auth.spec.ts        # Tests login flow itself (uses raw page)
├── editor.spec.ts      # User tests (use userPage fixture)
├── settings.spec.ts    # User tests (use userPage fixture)
├── home.spec.ts        # Public tests (use raw page)
└── admin-*.spec.ts     # Admin tests (use adminPage fixture)
```

### Fixture types

Tests use different fixtures based on auth requirements:

| Fixture | Scope | Auth State |
|---------|-------|------------|
| `userPage` | Test | Pre-authenticated as regular user |
| `adminPage` | Test | Pre-authenticated as admin |
| `page` | Test | No auth (for public pages, login flow tests) |

### Writing tests

Tests request the appropriate fixture—the browser is already authenticated:

```typescript
// User tests: use userPage fixture
test('displays editor page', async ({ userPage }) => {
  await userPage.goto('/editor');
  await expect(userPage.getByRole('heading', { name: 'Code Editor' })).toBeVisible();
});

// Admin tests: use adminPage fixture
test('shows admin dashboard', async ({ adminPage }) => {
  await adminPage.goto('/admin/users');
  await expect(adminPage.getByRole('heading', { name: 'User Management' })).toBeVisible();
});

// Public page tests: use raw page
test('shows home page', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Welcome')).toBeVisible();
});
```

### Testing unauthenticated flows

For tests that need to verify login/logout behavior, use the raw `page` fixture with `clearSession()`:

```typescript
test('redirects unauthenticated users to login', async ({ page }) => {
  await clearSession(page);  // Clears cookies and storage
  await page.goto('/editor');
  await expect(page).toHaveURL(/\/login/);
});
```

## Configuration

Vitest configuration lives in [`vitest.config.ts`](https://github.com/HardMax71/Integr8sCode/blob/main/frontend/vitest.config.ts):

```typescript
--8<-- "frontend/vitest.config.ts:5:27"
```

The setup file [`vitest.setup.ts`](https://github.com/HardMax71/Integr8sCode/blob/main/frontend/vitest.setup.ts)
provides browser API mocks that jsdom lacks (localStorage, sessionStorage, matchMedia, ResizeObserver,
IntersectionObserver).

Playwright configuration in [`playwright.config.ts`](https://github.com/HardMax71/Integr8sCode/blob/main/frontend/playwright.config.ts):

```typescript
--8<-- "frontend/playwright.config.ts:3:25"
```

## Writing component tests

Component tests use @testing-library/svelte to render components and query the DOM. The library encourages testing from the user's perspective—query by role, label, or text rather than implementation details like CSS classes or component internals.

A typical component test renders the component, queries for elements, and asserts on the output:

```typescript
import { render, screen } from '@testing-library/svelte';
import Spinner from '../Spinner.svelte';

it('renders with accessible label', () => {
  render(Spinner);
  expect(screen.getByLabelText('Loading')).toBeInTheDocument();
});

it('applies size prop', () => {
  render(Spinner, { props: { size: 'large' } });
  const svg = screen.getByRole('status');
  expect(svg.classList.contains('h-8')).toBe(true);
});
```

For components with user interactions, use `@testing-library/user-event`:

```typescript
import userEvent from '@testing-library/user-event';

it('calls reload on button click', async () => {
  const user = userEvent.setup();
  render(ErrorDisplay, { props: { error: 'Something broke' } });

  await user.click(screen.getByRole('button', { name: /Reload/i }));
  expect(window.location.reload).toHaveBeenCalled();
});
```

Svelte 5 components using transitions need the Web Animations API mocked:

```typescript
Element.prototype.animate = vi.fn().mockImplementation(() => ({
  onfinish: null,
  cancel: vi.fn(),
  finish: vi.fn(),
}));
```

## Testing stores

Svelte stores are plain JavaScript, so they test without any special setup. Import the store, call its methods, and check the current value with `get()`:

```typescript
import { get } from 'svelte/store';
import { toasts, addToast, removeToast } from '../toastStore';

beforeEach(() => {
  toasts.set([]);
});

it('adds toast with correct type', () => {
  addToast('Success!', 'success');
  const current = get(toasts);
  expect(current[0].type).toBe('success');
});
```

For stores that persist to localStorage, mock the storage API and use `vi.resetModules()` to get fresh module state between tests:

```typescript
beforeEach(async () => {
  vi.mocked(localStorage.getItem).mockReturnValue(null);
  vi.resetModules();
});

it('restores from localStorage', async () => {
  localStorage.getItem.mockReturnValue(JSON.stringify({ theme: 'dark' }));
  const { theme } = await import('../theme');
  expect(get(theme)).toBe('dark');
});
```

## Mocking API calls

API functions are mocked at the module level using `vi.mock()`. Define mock functions at the top of the file, then configure their return values per test:

```typescript
const mockLoginApi = vi.fn();
vi.mock('../../lib/api', () => ({
  loginApiV1AuthLoginPost: (...args) => mockLoginApi(...args),
}));

beforeEach(() => {
  mockLoginApi.mockReset();
});

it('handles successful login', async () => {
  mockLoginApi.mockResolvedValue({
    data: { username: 'testuser', role: 'user', csrf_token: 'token' },
    error: null,
  });

  const { login, isAuthenticated } = await import('../auth');
  await login('testuser', 'password');

  expect(get(isAuthenticated)).toBe(true);
});
```

## CI integration

The frontend CI workflow runs tests as part of the build process. Unit tests run first, and if they pass, e2e tests run against the built application. Coverage reports go to Codecov for tracking.

```yaml
- name: Run unit tests
  run: npm run test:coverage

- name: Run e2e tests
  run: npm run test:e2e
```

Tests timeout after 5 minutes for unit tests and 10 minutes for e2e. If you're adding slow tests, consider whether they belong in the e2e suite rather than unit tests.

## Troubleshooting

When tests fail with "Cannot read properties of undefined (reading 'matches')", you're missing the matchMedia mock. Add it to your test file or ensure vitest.setup.ts is loading correctly.

Svelte transition errors like "element.animate is not a function" mean you need to mock the Web Animations API. Add the animate mock before rendering components that use `fly`, `fade`, or other transitions.

Timing issues with fake timers and async components usually mean you're mixing `vi.useFakeTimers()` with `waitFor()`. Either use real timers for that test or manually advance time with `vi.advanceTimersByTimeAsync()`.

Store tests that bleed state between runs need `vi.resetModules()` in beforeEach. This clears the module cache so each test gets fresh store instances.
