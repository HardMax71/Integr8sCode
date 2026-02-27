import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { user } from '$test/test-utils';
import ModalWrapper from './ModalWrapper.svelte';

describe('Modal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('open/closed', () => {
    it.each([
      { open: true, visible: true },
      { open: false, visible: false },
    ])('content visible=$visible when open=$open', ({ open, visible }) => {
      render(ModalWrapper, { props: { open } });
      if (visible) {
        expect(screen.getByTestId('modal-body')).toBeInTheDocument();
      } else {
        expect(screen.queryByTestId('modal-body')).not.toBeInTheDocument();
      }
    });
  });

  describe('accessibility', () => {
    it('has correct dialog a11y attributes', () => {
      render(ModalWrapper, { props: { open: true } });
      const dialog = screen.getByRole('dialog');
      expect(dialog).toHaveAttribute('aria-modal', 'true');
      expect(dialog).toHaveAttribute('aria-labelledby', 'modal-title');
      expect(screen.getByText('Test Modal')).toHaveAttribute('id', 'modal-title');
      expect(screen.getByRole('button', { name: 'Close modal' })).toBeInTheDocument();
    });
  });

  describe('close interactions', () => {
    it('fires onClose when X button clicked', async () => {
      const onClose = vi.fn();
      render(ModalWrapper, { props: { open: true, onClose } });
      await user.click(screen.getByRole('button', { name: 'Close modal' }));
      expect(onClose).toHaveBeenCalledOnce();
    });

    it('fires onClose on Escape keydown', async () => {
      const onClose = vi.fn();
      render(ModalWrapper, { props: { open: true, onClose } });
      await fireEvent.keyDown(window, { key: 'Escape' });
      expect(onClose).toHaveBeenCalled();
    });

    it('fires onClose on backdrop click', async () => {
      const onClose = vi.fn();
      render(ModalWrapper, { props: { open: true, onClose } });
      await fireEvent.click(screen.getByRole('dialog'));
      expect(onClose).toHaveBeenCalledOnce();
    });

    it('does not fire onClose when clicking body content', async () => {
      const onClose = vi.fn();
      render(ModalWrapper, { props: { open: true, onClose } });
      await user.click(screen.getByTestId('modal-body'));
      expect(onClose).not.toHaveBeenCalled();
    });
  });

  describe('size classes', () => {
    it.each([
      { size: 'sm' as const, expectedClass: 'max-w-md' },
      { size: 'md' as const, expectedClass: 'max-w-2xl' },
      { size: 'lg' as const, expectedClass: 'max-w-4xl' },
      { size: 'xl' as const, expectedClass: 'max-w-6xl' },
    ])('applies $expectedClass for size=$size', ({ size, expectedClass }) => {
      const { container } = render(ModalWrapper, { props: { open: true, size } });
      expect(container.querySelector('.modal-container')?.classList.contains(expectedClass)).toBe(true);
    });

    it('defaults to lg (max-w-4xl)', () => {
      const { container } = render(ModalWrapper, { props: { open: true } });
      expect(container.querySelector('.modal-container')?.classList.contains('max-w-4xl')).toBe(true);
    });
  });

  describe('footer', () => {
    it.each([
      { showFooter: true, hasFooter: true },
      { showFooter: false, hasFooter: false },
    ])('footer present=$hasFooter when showFooter=$showFooter', ({ showFooter, hasFooter }) => {
      const { container } = render(ModalWrapper, { props: { open: true, showFooter } });
      if (hasFooter) {
        expect(screen.getByTestId('modal-footer-content')).toBeInTheDocument();
      } else {
        expect(container.querySelector('.modal-footer')).not.toBeInTheDocument();
      }
    });
  });
});
