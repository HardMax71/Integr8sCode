import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';

const mocks = vi.hoisted(() => ({
  scrollTo: vi.fn(),
}));

beforeEach(() => {
  vi.stubGlobal('scrollTo', mocks.scrollTo);
});

describe('Privacy', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  async function renderPrivacy() {
    const { default: Privacy } = await import('$routes/Privacy.svelte');
    return render(Privacy);
  }

  it('renders heading "Privacy Policy" and last updated date', async () => {
    await renderPrivacy();
    expect(screen.getByRole('heading', { name: /privacy policy/i, level: 1 })).toBeInTheDocument();
    expect(screen.getByText(/last updated: august 30, 2025/i)).toBeInTheDocument();
  });

  it('renders operator info: name, email, and location', async () => {
    await renderPrivacy();
    expect(screen.getAllByText(/Max Azatian/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/max\.azatian@gmail\.com/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Germany/).length).toBeGreaterThan(0);
  });

  it.each([
    'Hi there!',
    "Who's responsible for your data?",
    'What information do I collect?',
    'Why do I need this information?',
    'How long do I keep your data?',
    'Who else sees your data?',
    'How do I protect your data?',
    'Your rights (GDPR stuff)',
    "Where's your data stored?",
    'About cookies',
    'Kids and this service',
    'The tech stack',
    'Changes to this policy',
    'Get in touch',
  ])('renders section heading "%s"', async (heading) => {
    await renderPrivacy();
    expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument();
  });

  it('calls window.scrollTo(0, 0) on mount', async () => {
    await renderPrivacy();
    expect(mocks.scrollTo).toHaveBeenCalledWith(0, 0);
  });

  it.each([
    'mailto:max.azatian@gmail.com',
    'mailto:max.azatian@gmail.com?subject=GDPR%20Request',
    'mailto:max.azatian@gmail.com?subject=Minor%20Account%20Concern',
    'mailto:max.azatian@gmail.com?subject=Privacy%20Question',
    'mailto:max.azatian@gmail.com?subject=Privacy%20Concern',
  ])('contains mailto link %s', async (href) => {
    await renderPrivacy();
    const links = screen.getAllByRole('link');
    const matchingLink = links.find(l => l.getAttribute('href') === href);
    expect(matchingLink).toBeTruthy();
  });
});
