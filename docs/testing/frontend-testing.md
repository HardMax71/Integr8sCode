# Frontend testing

The frontend uses Vitest for unit and integration tests, with Playwright for end-to-end scenarios. Tests live alongside the source code in `__tests__` directories, following the same structure as the components they verify. The setup uses jsdom for DOM simulation and @testing-library/svelte for component rendering, giving you a realistic browser-like environment without the overhead of spinning up actual browsers for every test run.

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

## Configuration

Vitest configuration lives in `vitest.config.ts`:

```typescript
export default defineConfig({
  plugins: [svelte({ compilerOptions: { runes: true } }), svelteTesting()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    include: ['src/**/*.{test,spec}.{js,ts}'],
    globals: true,
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,svelte}'],
      exclude: ['src/lib/api/**', 'src/**/*.test.ts'],
    },
  },
});
```

The setup file (`vitest.setup.ts`) provides browser API mocks that jsdom lacks:

```typescript
// localStorage and sessionStorage mocks
vi.stubGlobal('localStorage', localStorageMock);
vi.stubGlobal('sessionStorage', sessionStorageMock);

// matchMedia for theme detection
vi.stubGlobal('matchMedia', vi.fn().mockImplementation(query => ({
  matches: false,
  media: query,
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
})));

// ResizeObserver and IntersectionObserver for layout-dependent components
vi.stubGlobal('ResizeObserver', vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
})));
```

Playwright configuration in `playwright.config.ts` sets up browser testing:

```typescript
export default defineConfig({
  testDir: './e2e',
  timeout: 10000,
  use: {
    baseURL: 'https://localhost:5001',
    screenshot: 'only-on-failure',
    trace: 'on',
  },
});
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
