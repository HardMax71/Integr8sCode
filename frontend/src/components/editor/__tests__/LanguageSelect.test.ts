import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, within, fireEvent, waitFor } from '@testing-library/svelte';
import { user } from '$test/test-utils';


import LanguageSelect from '../LanguageSelect.svelte';

const RUNTIMES = {
  python: { versions: ['3.11', '3.10', '3.9'], file_ext: 'py' },
  node: { versions: ['20', '18'], file_ext: 'js' },
  go: { versions: ['1.21'], file_ext: 'go' },
};

const defaultProps = { runtimes: RUNTIMES, lang: 'python', version: '3.11', onselect: vi.fn() };

function renderSelect(overrides: Partial<typeof defaultProps> = {}) {
  const props = { ...defaultProps, onselect: vi.fn(), ...overrides };
  return { ...render(LanguageSelect, { props }), onselect: props.onselect };
}

describe('LanguageSelect', () => {
  async function openMenu() {
    const result = renderSelect();
    await user.click(screen.getByRole('button', { name: /Select language/i }));
    return result;
  }

  describe('trigger button', () => {
    it('shows current language and version with aria-haspopup', () => {
      renderSelect();
      const btn = screen.getByRole('button', { name: /Select language/i });
      expect(btn).toBeInTheDocument();
      expect(btn).toHaveAttribute('aria-haspopup', 'menu');
    });

    it('shows "Unavailable" and is disabled when no runtimes', () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      renderSelect({ runtimes: {} as any });
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
      await openMenu();
      await user.click(screen.getByRole('button', { name: /Select language/i }));
      await waitFor(() => {
        expect(screen.queryByRole('menu', { name: 'Select language and version' })).not.toBeInTheDocument();
      });
    });
  });

  describe('version submenu', () => {
    it('shows all versions on language hover with correct aria-checked', async () => {
      await openMenu();
      await user.hover(screen.getByRole('menuitem', { name: /python/i }));
      const versionMenu = screen.getByRole('menu', { name: /python versions/i });
      const versions = within(versionMenu).getAllByRole('menuitemradio');
      expect(versions).toHaveLength(3);
      expect(within(versionMenu).getByRole('menuitemradio', { name: '3.11' })).toHaveAttribute('aria-checked', 'true');
      expect(within(versionMenu).getByRole('menuitemradio', { name: '3.10' })).toHaveAttribute('aria-checked', 'false');
    });

    it('calls onselect and closes menu on version click', async () => {
      const { onselect } = await openMenu();
      await user.hover(screen.getByRole('menuitem', { name: /node/i }));
      const nodeMenu = screen.getByRole('menu', { name: /node versions/i });
      await user.click(within(nodeMenu).getByRole('menuitemradio', { name: '20' }));
      expect(onselect).toHaveBeenCalledWith('node', '20');
      await waitFor(() => {
        expect(screen.queryByRole('menu', { name: 'Select language and version' })).not.toBeInTheDocument();
      });
    });

    it('switches version submenu when hovering different language', async () => {
      await openMenu();
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
      { key: ' ', label: 'Space' },
    ])('opens menu with $label on trigger', async ({ key }) => {
      renderSelect();
      screen.getByRole('button', { name: /Select language/i }).focus();
      await user.keyboard(key);
      expect(screen.getByRole('menu', { name: 'Select language and version' })).toBeInTheDocument();
    });

    it('closes menu with Escape on trigger', async () => {
      await openMenu();
      const trigger = screen.getByRole('button', { name: /Select language/i });
      await fireEvent.keyDown(trigger, { key: 'Escape' });
      await waitFor(() => {
        expect(screen.queryByRole('menu', { name: 'Select language and version' })).not.toBeInTheDocument();
      });
    });
  });

  describe('menu keyboard navigation', () => {
    async function openMenuAndGetMenu() {
      const result = renderSelect();
      await user.click(screen.getByRole('button', { name: /Select language/i }));
      const menu = screen.getByRole('menu', { name: 'Select language and version' });
      return { ...result, menu };
    }

    it.each([
      { key: 'ArrowDown', presses: 1, expectedIndex: 1, desc: 'moves focus to next language' },
      { key: 'ArrowDown', presses: 3, expectedIndex: 2, desc: 'clamps at last language' },
      { key: 'ArrowUp', presses: 1, expectedIndex: 0, desc: 'clamps at first language' },
    ])('$key $desc', async ({ key, presses, expectedIndex }) => {
      const { menu } = await openMenuAndGetMenu();
      for (let i = 0; i < presses; i++) {
        await fireEvent.keyDown(menu, { key });
      }
      const items = screen.getAllByRole('menuitem');
      expect(items[expectedIndex]).toHaveAttribute('tabindex', '0');
    });

    it('ArrowUp moves focus to previous language', async () => {
      const { menu } = await openMenuAndGetMenu();
      await fireEvent.keyDown(menu, { key: 'ArrowDown' }); // index 1
      await fireEvent.keyDown(menu, { key: 'ArrowUp' }); // back to 0
      const items = screen.getAllByRole('menuitem');
      expect(items[0]).toHaveAttribute('tabindex', '0');
    });

    it.each([
      { key: 'ArrowRight', label: 'ArrowRight' },
      { key: 'Enter', label: 'Enter' },
      { key: ' ', label: 'Space' },
    ])('$label on language opens version submenu', async ({ key }) => {
      const { menu } = await openMenuAndGetMenu();
      await fireEvent.keyDown(menu, { key });
      expect(screen.getByRole('menu', { name: /python versions/i })).toBeInTheDocument();
    });

    it.each([
      { key: 'ArrowDown', presses: 1, expectedIndex: 1, desc: 'moves to next version' },
      { key: 'ArrowDown', presses: 3, expectedIndex: 2, desc: 'clamps at last version' },
      { key: 'ArrowUp', presses: 1, expectedIndex: 0, desc: 'clamps at first version' },
    ])('$key in submenu $desc', async ({ key, presses, expectedIndex }) => {
      const { menu } = await openMenuAndGetMenu();
      await fireEvent.keyDown(menu, { key: 'ArrowRight' }); // open python submenu
      for (let i = 0; i < presses; i++) {
        await fireEvent.keyDown(menu, { key });
      }
      const versionMenu = screen.getByRole('menu', { name: /python versions/i });
      const versions = within(versionMenu).getAllByRole('menuitemradio');
      expect(versions[expectedIndex]).toHaveAttribute('tabindex', '0');
    });

    it('ArrowUp in submenu moves to previous version', async () => {
      const { menu } = await openMenuAndGetMenu();
      await fireEvent.keyDown(menu, { key: 'ArrowRight' });
      await fireEvent.keyDown(menu, { key: 'ArrowDown' }); // index 1
      await fireEvent.keyDown(menu, { key: 'ArrowUp' }); // back to 0
      const versionMenu = screen.getByRole('menu', { name: /python versions/i });
      const versions = within(versionMenu).getAllByRole('menuitemradio');
      expect(versions[0]).toHaveAttribute('tabindex', '0');
    });

    it.each([
      { key: 'Enter', label: 'Enter' },
      { key: ' ', label: 'Space' },
    ])('$label in submenu selects version and closes menu', async ({ key }) => {
      const { onselect, menu } = await openMenuAndGetMenu();
      await fireEvent.keyDown(menu, { key: 'ArrowRight' }); // open python submenu
      await fireEvent.keyDown(menu, { key: 'ArrowDown' }); // move to version index 1 (3.10)
      await fireEvent.keyDown(menu, { key });
      expect(onselect).toHaveBeenCalledWith('python', '3.10');
      await waitFor(() => {
        expect(screen.queryByRole('menu', { name: 'Select language and version' })).not.toBeInTheDocument();
      });
    });

    it.each([
      { key: 'ArrowLeft', label: 'ArrowLeft' },
      { key: 'Escape', label: 'Escape' },
    ])('$label in submenu exits submenu but keeps main menu', async ({ key }) => {
      const { menu } = await openMenuAndGetMenu();
      await fireEvent.keyDown(menu, { key: 'ArrowRight' }); // open python submenu
      expect(screen.getByRole('menu', { name: /python versions/i })).toBeInTheDocument();
      await fireEvent.keyDown(menu, { key });
      await waitFor(() => {
        expect(screen.queryByRole('menu', { name: /python versions/i })).not.toBeInTheDocument();
      });
      expect(screen.getByRole('menu', { name: 'Select language and version' })).toBeInTheDocument();
    });

    it('Escape in root menu closes entire menu', async () => {
      const { menu } = await openMenuAndGetMenu();
      await fireEvent.keyDown(menu, { key: 'Escape' });
      await waitFor(() => {
        expect(screen.queryByRole('menu', { name: 'Select language and version' })).not.toBeInTheDocument();
      });
    });
  });
});
