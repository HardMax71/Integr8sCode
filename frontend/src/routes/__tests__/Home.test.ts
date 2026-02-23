import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
const mocks = vi.hoisted(() => ({
  mockUpdateMetaTags: vi.fn(),
}));

vi.mock('@mateothegreat/svelte5-router', async () =>
  (await import('$test/test-utils')).createMockRouterModule());

vi.mock('$utils/meta', async () =>
  (await import('$test/test-utils')).createMetaMock(
    mocks.mockUpdateMetaTags, { home: { title: 'Home', description: 'Home desc' } }));

vi.mock('@lucide/svelte', async () =>
  (await import('$test/test-utils')).createMockIconModule('Zap', 'ShieldCheck', 'Clock'));

describe('Home', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  async function renderHome() {
    const { default: Home } = await import('$routes/Home.svelte');
    return render(Home);
  }

  it('renders hero heading with "Code, Run,", "Integrate", and "Instantly."', async () => {
    await renderHome();
    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
    });
    const heading = screen.getByRole('heading', { level: 1 });
    expect(heading.textContent).toContain('Code, Run,');
    expect(heading.textContent).toContain('Integrate');
    expect(heading.textContent).toContain('Instantly.');
  });

  it('renders CTA link "Start Coding Now" with href="/editor"', async () => {
    await renderHome();
    await waitFor(() => {
      expect(screen.getByRole('link', { name: /start coding now/i })).toBeInTheDocument();
    });
    expect(screen.getByRole('link', { name: /start coding now/i })).toHaveAttribute('href', '/editor');
  });

  it.each([
    ['Instant Execution', 'Run code online effortlessly in isolated Kubernetes pods with near-native speed.'],
    ['Secure & Efficient', 'Strict resource limits (CPU, Memory, Time) and network restrictions ensure safe code execution.'],
    ['Real-time Results', 'Get immediate feedback with live execution status updates and detailed output upon completion.'],
  ])('renders feature "%s" with description', async (title, content) => {
    await renderHome();
    await waitFor(() => {
      expect(screen.getByText(title)).toBeInTheDocument();
    });
    expect(screen.getByText(content)).toBeInTheDocument();
  });

  it('calls updateMetaTags with home meta on mount', async () => {
    await renderHome();
    await waitFor(() => {
      expect(mocks.mockUpdateMetaTags).toHaveBeenCalledWith('Home', 'Home desc');
    });
  });
});
