import { describe, it, expect, vi } from 'vitest';
import { screen, within, waitFor } from '@testing-library/svelte';
import { mockApi, renderWithQueryClient, user } from '#test/test-utils.ts';
import { fakeResourceLimits } from '#lib/api/@faker-js/faker.gen.ts';

import LanguageSelect from '#components/editor/LanguageSelect.svelte';
import { getK8sResourceLimitsApiV1K8sLimitsGet, type ResourceLimits } from '#lib/api/index.ts';
import { draft } from '#lib/editor/draft.svelte.ts';

const RUNTIMES: ResourceLimits['supported_runtimes'] = {
    python: { versions: ['3.14', '3.13', '3.12'], file_ext: 'py' },
    node: { versions: ['26', '24', '22'], file_ext: 'js' },
    go: { versions: ['1.27'], file_ext: 'go' },
};

function renderSelect({ runtimes = RUNTIMES, lang = 'python', version = '3.14' } = {}) {
    mockApi(getK8sResourceLimitsApiV1K8sLimitsGet).ok({ ...fakeResourceLimits(), supported_runtimes: runtimes });
    draft.current = { ...draft.current, lang, lang_version: version };
    return renderWithQueryClient(LanguageSelect);
}

const selection = () => [draft.current.lang, draft.current.lang_version];

function trigger(): HTMLElement {
    return screen.getByRole('button', { name: /Select language/i });
}

function mainMenu(): HTMLElement | null {
    return screen.queryByRole('menu', { name: 'Select language and version' });
}

async function openMenu(): Promise<void> {
    renderSelect();
    await waitFor(() => expect(trigger()).toBeEnabled());
    await user.click(trigger());
}

async function openWithKeyboard(): Promise<void> {
    renderSelect();
    await waitFor(() => expect(trigger()).toBeEnabled());
    trigger().focus();
    await user.keyboard('{Enter}');
    await waitFor(() => expect(screen.getByRole('menuitem', { name: 'python' })).toHaveFocus());
}

describe('LanguageSelect', () => {
    describe('trigger button', () => {
        it('shows current language and version with aria-haspopup', () => {
            renderSelect();
            const btn = screen.getByRole('button', { name: /Select language/i });
            expect(btn).toBeInTheDocument();
            expect(btn).toHaveAttribute('aria-haspopup', 'menu');
        });

        it('shows "Unavailable" and is disabled when no runtimes', async () => {
            renderSelect({ runtimes: {} });
            await waitFor(() => expect(vi.mocked(getK8sResourceLimitsApiV1K8sLimitsGet)).toHaveBeenCalled());
            expect(screen.getByText('Unavailable')).toBeInTheDocument();
            expect(screen.getByRole('button')).toBeDisabled();
        });
    });

    describe('runtimes the API no longer offers', () => {
        it.each([
            {
                name: "its language's newest version for a dropped version",
                lang: 'python',
                version: '3.7',
                shown: 'python 3.14',
            },
            {
                name: 'the first offered language for a dropped language',
                lang: 'cobol',
                version: '85',
                shown: 'python 3.14',
            },
            { name: 'an offered version as it is', lang: 'python', version: '3.13', shown: 'python 3.13' },
        ])('shows $name and leaves the draft alone', async ({ lang, version, shown }) => {
            renderSelect({ lang, version });
            await waitFor(() => expect(trigger()).toHaveTextContent(shown));
            expect(selection()).toEqual([lang, version]);
        });
    });

    describe('menu', () => {
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
            await openMenu();
            await user.hover(screen.getByRole('menuitem', { name: 'node' }));
            const versions = await screen.findByRole('menu', { name: /node/i });
            await user.click(within(versions).getByRole('menuitemradio', { name: '24' }));
            expect(selection()).toEqual(['node', '24']);
            await waitFor(() => expect(mainMenu()).not.toBeInTheDocument());
        });

        it('selects a version with the keyboard alone', async () => {
            await openWithKeyboard();
            await user.keyboard('{ArrowRight}');
            await screen.findByRole('menu', { name: /python/i });
            await user.keyboard('{ArrowDown}{Enter}');
            expect(selection()).toEqual(['python', '3.13']);
            await waitFor(() => expect(mainMenu()).not.toBeInTheDocument());
        });

        it('closes on Escape and gives focus back to the trigger', async () => {
            await openWithKeyboard();
            await user.keyboard('{Escape}');
            await waitFor(() => expect(mainMenu()).not.toBeInTheDocument());
            expect(screen.getByRole('button', { name: /Select language/i })).toHaveFocus();
        });
    });
});
