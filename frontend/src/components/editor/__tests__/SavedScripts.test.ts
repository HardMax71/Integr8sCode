import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { user } from '$test/test-utils';


import SavedScripts from '../SavedScripts.svelte';
import type { SavedScriptResponse } from '$lib/api';

function createScripts(count: number): SavedScriptResponse[] {
  return Array.from({ length: count }, (_, i) => ({
    script_id: `script-${i + 1}`,
    name: `Script ${i + 1}`,
    script: `print("hello ${i + 1}")`,
    lang: 'python',
    lang_version: '3.11',
    description: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }));
}

function renderScripts(scripts: SavedScriptResponse[] = []) {
  const onload = vi.fn();
  const ondelete = vi.fn();
  const onrefresh = vi.fn();
  const result = render(SavedScripts, { props: { scripts, onload, ondelete, onrefresh } });
  return { ...result, onload, ondelete, onrefresh };
}

describe('SavedScripts', () => {
  async function renderAndExpand(scripts: SavedScriptResponse[] = []) {
    const result = renderScripts(scripts);
    await user.click(screen.getByRole('button', { name: /Show Saved Scripts/i }));
    return result;
  }

  it('renders collapsed with heading, toggle button, and scripts hidden', () => {
    renderScripts(createScripts(2));
    expect(screen.getByText('Saved Scripts')).toBeInTheDocument();
    const btn = screen.getByRole('button', { name: /Show Saved Scripts/i });
    expect(btn).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Script 1')).not.toBeInTheDocument();
  });

  it('calls onrefresh only when expanding, not when collapsing', async () => {
    const { onrefresh } = await renderAndExpand();
    expect(onrefresh).toHaveBeenCalledOnce();
    onrefresh.mockClear();

    await user.click(screen.getByRole('button', { name: /Hide Saved Scripts/i }));
    expect(onrefresh).not.toHaveBeenCalled();
  });

  it('shows empty state when no scripts', async () => {
    await renderAndExpand();
    expect(screen.getByText('No saved scripts yet.')).toBeInTheDocument();
  });

  it('shows all script names when expanded', async () => {
    const scripts = createScripts(3);
    await renderAndExpand(scripts);
    for (const s of scripts) {
      expect(screen.getByText(s.name)).toBeInTheDocument();
    }
  });

  it.each([
    { lang: 'go', lang_version: '1.21', expected: 'go 1.21' },
    { lang: 'python', lang_version: '3.12', expected: 'python 3.12' },
  ])('displays "$expected" for lang=$lang version=$lang_version', async ({ lang, lang_version, expected }) => {
    await renderAndExpand([{ script_id: '1', name: 'Test', script: 'x', lang, lang_version, description: null, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }]);
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it('calls onload with full script object when clicking a script name', async () => {
    const scripts = createScripts(2);
    const { onload } = await renderAndExpand(scripts);
    await user.click(screen.getByText('Script 2'));
    expect(onload).toHaveBeenCalledWith(scripts[1]);
  });

  it('calls ondelete with script id and does not trigger onload (stopPropagation)', async () => {
    const scripts = createScripts(1);
    const { onload, ondelete } = await renderAndExpand(scripts);
    await user.click(screen.getByTitle('Delete Script 1'));
    expect(ondelete).toHaveBeenCalledWith('script-1');
    expect(onload).not.toHaveBeenCalled();
  });

  it('renders load button title with lang info', async () => {
    await renderAndExpand([{ script_id: '1', name: 'Go App', script: 'x', lang: 'go', lang_version: '1.21', description: null, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }]);
    expect(screen.getByTitle('Load Go App (go 1.21)')).toBeInTheDocument();
  });
});
