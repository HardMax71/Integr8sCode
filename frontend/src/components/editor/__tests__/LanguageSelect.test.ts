import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, within, fireEvent, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { setupAnimationMock } from '../../../__tests__/test-utils';

vi.mock('@lucide/svelte', async () =>
  (await import('../../../__tests__/test-utils')).createMockIconModule('ChevronDown', 'ChevronRight'));

import LanguageSelect from '../LanguageSelect.svelte';

const RUNTIMES = {
  python: { versions: ['3.11', '3.10', '3.9'], image: '', display_name: 'Python' },
  node: { versions: ['20', '18'], image: '', display_name: 'Node' },
  go: { versions: ['1.21'], image: '', display_name: 'Go' },
};

const defaultProps = { runtimes: RUNTIMES, lang: 'python', version: '3.11', onselect: vi.fn() };

function renderSelect(overrides: Partial<typeof defaultProps> = {}) {
  const props = { ...defaultProps, onselect: vi.fn(), ...overrides };
  return { ...render(LanguageSelect, { props }), onselect: props.onselect };
}

async function openMenu() {
  const user = userEvent.setup();
  const result = renderSelect();
  await user.click(screen.getByRole('button', { name: /python 3\.11/i }));
  return { user, ...result };
}

describe('LanguageSelect', () => {
  beforeEach(() => {
    setupAnimationMock();
  });

  describe('trigger button', () => {
    it('shows current language and version with aria-haspopup', () => {
      renderSelect();
      const btn = screen.getByRole('button', { name: /python 3\.11/i });
      expect(btn).toBeInTheDocument();
      expect(btn).toHaveAttribute('aria-haspopup', 'menu');
    });

    it('shows "Unavailable" and is disabled when no runtimes', () => {
      renderSelect({ runtimes: {} });
      expect(screen.getByText('Unavailable')).toBeInTheDocument();
      expect(screen.getByRole('button')).toBeDisabled();
    });
  });

  describe('dropdown menu', () => {
    it('opens on click and lists all languages', async () => {
      await openMenu();
      expect(screen.getByRole('menu', { name: 'Select language and version' })).toBeInTheDocument();
      expect(screen.getByRole('menuitem', { name: /python/i })).toBeInTheDocument();
      expect(screen.getByRole('menuitem', { name: /node/i })).toBeInTheDocument();
      expect(screen.getByRole('menuitem', { name: /go/i })).toBeInTheDocument();
    });

    it('closes menu on second click', async () => {
      const { user } = await openMenu();
      await user.click(screen.getByRole('button', { name: /python 3\.11/i }));
      await waitFor(() => {
        expect(screen.queryByRole('menu', { name: 'Select language and version' })).not.toBeInTheDocument();
      });
    });
  });

  describe('version submenu', () => {
    it('shows all versions on language hover with correct aria-checked', async () => {
      const { user } = await openMenu();
      await user.hover(screen.getByRole('menuitem', { name: /python/i }));
      const versionMenu = screen.getByRole('menu', { name: /python versions/i });
      const versions = within(versionMenu).getAllByRole('menuitemradio');
      expect(versions).toHaveLength(3);
      expect(within(versionMenu).getByRole('menuitemradio', { name: '3.11' })).toHaveAttribute('aria-checked', 'true');
      expect(within(versionMenu).getByRole('menuitemradio', { name: '3.10' })).toHaveAttribute('aria-checked', 'false');
    });

    it('calls onselect and closes menu on version click', async () => {
      const { user, onselect } = await openMenu();
      await user.hover(screen.getByRole('menuitem', { name: /node/i }));
      const nodeMenu = screen.getByRole('menu', { name: /node versions/i });
      await user.click(within(nodeMenu).getByRole('menuitemradio', { name: '20' }));
      expect(onselect).toHaveBeenCalledWith('node', '20');
      await waitFor(() => {
        expect(screen.queryByRole('menu', { name: 'Select language and version' })).not.toBeInTheDocument();
      });
    });

    it('switches version submenu when hovering different language', async () => {
      const { user } = await openMenu();
      await user.hover(screen.getByRole('menuitem', { name: /python/i }));
      expect(screen.getByRole('menu', { name: /python versions/i })).toBeInTheDocument();

      await user.hover(screen.getByRole('menuitem', { name: /node/i }));
      await waitFor(() => {
        expect(screen.queryByRole('menu', { name: /python versions/i })).not.toBeInTheDocument();
      });
      expect(screen.getByRole('menu', { name: /node versions/i })).toBeInTheDocument();
    });
  });

  describe('keyboard navigation', () => {
    it.each([
      { key: '{ArrowDown}', label: 'ArrowDown' },
      { key: '{Enter}', label: 'Enter' },
    ])('opens menu with $label on trigger', async ({ key }) => {
      const user = userEvent.setup();
      renderSelect();
      screen.getByRole('button', { name: /python 3\.11/i }).focus();
      await user.keyboard(key);
      expect(screen.getByRole('menu', { name: 'Select language and version' })).toBeInTheDocument();
    });

    it('closes menu with Escape on trigger', async () => {
      await openMenu();
      const trigger = screen.getByRole('button', { name: /python 3\.11/i });
      await fireEvent.keyDown(trigger, { key: 'Escape' });
      await waitFor(() => {
        expect(screen.queryByRole('menu', { name: 'Select language and version' })).not.toBeInTheDocument();
      });
    });
  });
});
