import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import { user } from '#test/test-utils.ts';
import { toast } from 'svelte-sonner';

import LanguageSelect from '#components/editor/LanguageSelect.svelte';
import type { LanguageInfo } from '#lib/api/index.ts';

const RUNTIMES: Record<string, LanguageInfo> = {
    python: { versions: ['3.14', '3.13', '3.12'], file_ext: 'py' },
    node: { versions: ['26', '24', '22'], file_ext: 'js' },
    go: { versions: ['1.27'], file_ext: 'go' },
};

const defaultProps = { runtimes: RUNTIMES, lang: 'python', version: '3.14', onselect: vi.fn() };

function renderSelect(overrides: Partial<typeof defaultProps> = {}) {
    const props = { ...defaultProps, onselect: vi.fn(), ...overrides };
    return { ...render(LanguageSelect, { props }), onselect: props.onselect };
}

describe('LanguageSelect', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

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
            renderSelect({ runtimes: {} });
            expect(screen.getByText('Unavailable')).toBeInTheDocument();
            expect(screen.getByRole('button')).toBeDisabled();
        });
    });

    describe('dropped versions', () => {
        it('switches to the newest offered version when the current one is no longer offered', async () => {
            const runtimes = { ...RUNTIMES, python: { versions: ['3.12', '3.14', '3.13'], file_ext: 'py' } };
            const { onselect } = renderSelect({ runtimes, version: '3.7' });
            await waitFor(() => {
                expect(onselect).toHaveBeenCalledWith('python', '3.14');
            });
            expect(onselect).toHaveBeenCalledTimes(1);
            expect(toast.info).toHaveBeenCalledWith('Version 3.7 of python is no longer available, switched to 3.14.');
        });

        it.each([
            { desc: 'the version is offered', props: { version: '3.13' } },
            { desc: 'the language is unknown', props: { lang: 'cobol', version: '85' } },
            { desc: 'runtimes have not loaded', props: { runtimes: {}, version: '3.7' } },
        ])('leaves the selection alone when $desc', async ({ props }) => {
            const { onselect } = renderSelect(props);
            await tick();
            expect(onselect).not.toHaveBeenCalled();
            expect(toast.info).not.toHaveBeenCalled();
        });
    });

    describe('menu', () => {
        const mainMenu = () => screen.queryByRole('menu', { name: 'Select language and version' });

        it('lists every language, each opening its versions', async () => {
            await openMenu();
            expect(mainMenu()).toBeInTheDocument();
            for (const lang of ['python', 'node', 'go']) {
                expect(screen.getByRole('menuitem', { name: lang })).toHaveAttribute('aria-haspopup', 'menu');
            }
        });

        it('marks the current version as checked in its language', async () => {
            await openMenu();
            await user.hover(screen.getByRole('menuitem', { name: 'python' }));
            const versions = await screen.findByRole('menu', { name: /python/i });
            expect(within(versions).getAllByRole('menuitemradio')).toHaveLength(3);
            expect(within(versions).getByRole('menuitemradio', { name: '3.14' })).toHaveAttribute(
                'aria-checked',
                'true',
            );
            expect(within(versions).getByRole('menuitemradio', { name: '3.13' })).toHaveAttribute(
                'aria-checked',
                'false',
            );
        });

        it('selects a version with the mouse and closes', async () => {
            const { onselect } = await openMenu();
            await user.hover(screen.getByRole('menuitem', { name: 'node' }));
            const versions = await screen.findByRole('menu', { name: /node/i });
            await user.click(within(versions).getByRole('menuitemradio', { name: '24' }));
            expect(onselect).toHaveBeenCalledWith('node', '24');
            await waitFor(() => expect(mainMenu()).not.toBeInTheDocument());
        });

        it('selects a version with the keyboard alone', async () => {
            const { onselect } = renderSelect();
            screen.getByRole('button', { name: /Select language/i }).focus();
            await user.keyboard('{Enter}');
            await waitFor(() => expect(screen.getByRole('menuitem', { name: 'python' })).toHaveFocus());
            await user.keyboard('{ArrowRight}');
            await screen.findByRole('menu', { name: /python/i });
            await user.keyboard('{ArrowDown}{Enter}');
            expect(onselect).toHaveBeenCalledWith('python', '3.13');
            await waitFor(() => expect(mainMenu()).not.toBeInTheDocument());
        });

        it('closes on Escape and gives focus back to the trigger', async () => {
            renderSelect();
            screen.getByRole('button', { name: /Select language/i }).focus();
            await user.keyboard('{Enter}');
            await waitFor(() => expect(screen.getByRole('menuitem', { name: 'python' })).toHaveFocus());
            await user.keyboard('{Escape}');
            await waitFor(() => expect(mainMenu()).not.toBeInTheDocument());
            expect(screen.getByRole('button', { name: /Select language/i })).toHaveFocus();
        });
    });
});
