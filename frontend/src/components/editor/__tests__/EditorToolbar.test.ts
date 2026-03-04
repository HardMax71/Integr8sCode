import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { user } from '$test/test-utils';

import EditorToolbar from '$components/editor/EditorToolbar.svelte';

const defaultProps = {
    name: 'my_script.py',
    onexample: vi.fn(),
    onchange: vi.fn(),
};

function renderToolbar(overrides: Partial<typeof defaultProps> = {}) {
    const props = { ...defaultProps, onexample: vi.fn(), onchange: vi.fn(), ...overrides };
    return { ...render(EditorToolbar, { props }), props };
}

describe('EditorToolbar', () => {
    it('renders input with current name value', () => {
        renderToolbar({ name: 'hello.py' });
        expect(screen.getByRole('textbox', { name: /Script Name/i })).toHaveValue('hello.py');
    });

    it('input has accessible label', () => {
        renderToolbar();
        const input = screen.getByLabelText('Script Name');
        expect(input).toBeInTheDocument();
    });

    it('input has placeholder "Unnamed Script"', () => {
        renderToolbar({ name: '' });
        expect(screen.getByPlaceholderText('Unnamed Script')).toBeInTheDocument();
    });

    it('calls onchange when input value changes', async () => {
        const { props } = renderToolbar({ name: '' });
        const input = screen.getByRole('textbox', { name: /Script Name/i });
        await fireEvent.input(input, { target: { value: 'new_name.py' } });
        expect(props.onchange).toHaveBeenCalledWith('new_name.py');
    });

    it('renders Example button with correct title', () => {
        renderToolbar();
        const btn = screen.getByRole('button', { name: /Example/i });
        expect(btn).toBeInTheDocument();
        expect(btn).toHaveAttribute('title', 'Load an example script for the selected language');
        expect(btn).toHaveAttribute('type', 'button');
    });

    it('Example button click calls onexample', async () => {
        const { props } = renderToolbar();
        await user.click(screen.getByRole('button', { name: /Example/i }));
        expect(props.onexample).toHaveBeenCalledOnce();
    });
});
