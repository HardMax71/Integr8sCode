import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { user } from '$test/test-utils';

import ScriptActions from '$components/editor/ScriptActions.svelte';

const defaultProps = {
    authenticated: false,
    onnew: vi.fn(),
    onupload: vi.fn(),
    onsave: vi.fn(),
    onexport: vi.fn(),
};

function renderActions(overrides: Partial<typeof defaultProps> = {}) {
    const props = {
        ...defaultProps,
        onnew: vi.fn(),
        onupload: vi.fn(),
        onsave: vi.fn(),
        onexport: vi.fn(),
        ...overrides,
    };
    return { ...render(ScriptActions, { props }), props };
}

describe('ScriptActions', () => {
    it('renders heading "File Actions"', () => {
        renderActions();
        expect(screen.getByText('File Actions')).toBeInTheDocument();
    });

    it.each([
        { name: 'New', title: 'Start a new script' },
        { name: 'Upload', title: 'Upload a file' },
        { name: 'Export', title: 'Download current script' },
    ])('renders $name button with correct title and type', ({ name, title }) => {
        renderActions();
        const btn = screen.getByRole('button', { name: new RegExp(name) });
        expect(btn).toBeInTheDocument();
        expect(btn).toHaveAttribute('title', title);
        expect(btn).toHaveAttribute('type', 'button');
    });

    it('hides Save when not authenticated', () => {
        renderActions({ authenticated: false });
        expect(screen.queryByRole('button', { name: /Save/ })).not.toBeInTheDocument();
    });

    it('shows Save when authenticated', () => {
        renderActions({ authenticated: true });
        const btn = screen.getByRole('button', { name: /Save/ });
        expect(btn).toBeInTheDocument();
        expect(btn).toHaveAttribute('title', 'Save current script');
        expect(btn).toHaveAttribute('type', 'button');
    });

    it('renders 3 buttons when unauthenticated, 4 when authenticated', () => {
        const { unmount } = renderActions({ authenticated: false });
        expect(screen.getAllByRole('button')).toHaveLength(3);
        unmount();

        renderActions({ authenticated: true });
        expect(screen.getAllByRole('button')).toHaveLength(4);
    });

    it.each([
        { name: 'New', callbackKey: 'onnew' as const },
        { name: 'Upload', callbackKey: 'onupload' as const },
        { name: 'Export', callbackKey: 'onexport' as const },
    ])('$name button click calls $callbackKey', async ({ name, callbackKey }) => {
        const { props } = renderActions();
        await user.click(screen.getByRole('button', { name: new RegExp(name) }));
        expect(props[callbackKey]).toHaveBeenCalledOnce();
    });

    it('Save button click calls onsave when authenticated', async () => {
        const { props } = renderActions({ authenticated: true });
        await user.click(screen.getByRole('button', { name: /Save/ }));
        expect(props.onsave).toHaveBeenCalledOnce();
    });
});
