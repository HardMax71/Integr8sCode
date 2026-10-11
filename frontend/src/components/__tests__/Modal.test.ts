import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { user } from '#test/test-utils.ts';
import ModalWrapper from './ModalWrapper.svelte';

describe('Modal', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it.each([
        { open: true, visible: true },
        { open: false, visible: false },
    ])('content visible=$visible when open=$open', ({ open, visible }) => {
        render(ModalWrapper, { props: { open } });
        expect(!!screen.queryByTestId('modal-body')).toBe(visible);
    });

    it('is a modal dialog named by its title, with focus moved inside', async () => {
        render(ModalWrapper, { props: { open: true } });
        const dialog = screen.getByRole('dialog', { name: 'Test Modal' });
        await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
        expect(screen.getByRole('button', { name: 'Close dialog' })).toBeInTheDocument();
    });

    it('gives each open dialog its own title id', () => {
        render(ModalWrapper, { props: { open: true, title: 'First' } });
        render(ModalWrapper, { props: { open: true, title: 'Second' } });
        const first = screen.getByRole('dialog', { name: 'First' });
        const second = screen.getByRole('dialog', { name: 'Second' });
        expect(first.getAttribute('aria-labelledby')).not.toBe(second.getAttribute('aria-labelledby'));
    });

    describe('closing', () => {
        it('closes from the X button', async () => {
            const onClose = vi.fn();
            render(ModalWrapper, { props: { open: true, onClose } });
            await user.click(screen.getByRole('button', { name: 'Close dialog' }));
            expect(onClose).toHaveBeenCalledOnce();
        });

        it('closes on Escape', async () => {
            const onClose = vi.fn();
            render(ModalWrapper, { props: { open: true, onClose } });
            await waitFor(() => expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true));
            await user.keyboard('{Escape}');
            expect(onClose).toHaveBeenCalledOnce();
        });

        it('stays open when the body is clicked', async () => {
            const onClose = vi.fn();
            render(ModalWrapper, { props: { open: true, onClose } });
            await user.click(screen.getByTestId('modal-body'));
            expect(onClose).not.toHaveBeenCalled();
        });
    });

    it.each([
        { size: 'sm' as const, expectedClass: 'max-w-md' },
        { size: 'md' as const, expectedClass: 'max-w-2xl' },
        { size: 'lg' as const, expectedClass: 'max-w-4xl' },
        { size: 'xl' as const, expectedClass: 'max-w-6xl' },
        { size: undefined, expectedClass: 'max-w-4xl' },
    ])('applies $expectedClass for size=$size', ({ size, expectedClass }) => {
        render(ModalWrapper, { props: { open: true, size } });
        expect(screen.getByRole('dialog')).toHaveClass(expectedClass);
    });

    it.each([true, false])('renders the footer only when given one (footer=%s)', (showFooter) => {
        render(ModalWrapper, { props: { open: true, showFooter } });
        expect(!!screen.queryByTestId('modal-footer-content')).toBe(showFooter);
    });
});
