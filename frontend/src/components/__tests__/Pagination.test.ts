import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { user } from '$test/test-utils';
import Pagination from '$components/Pagination.svelte';

const defaultProps = {
  currentPage: 1,
  totalPages: 5,
  totalItems: 50,
  pageSize: 10,
  onPageChange: vi.fn(),
};

function renderPagination(overrides: Partial<typeof defaultProps> = {}) {
  const props = { ...defaultProps, onPageChange: vi.fn(), ...overrides };
  return { ...render(Pagination, { props }), onPageChange: props.onPageChange };
}

describe('Pagination', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('page info text', () => {
    it.each([
      { page: 1, totalPages: 5, totalItems: 50, pageSize: 10, expected: /Showing 1 - 10 of 50 items/ },
      { page: 3, totalPages: 5, totalItems: 50, pageSize: 10, expected: /Showing 21 - 30 of 50 items/ },
      { page: 3, totalPages: 3, totalItems: 23, pageSize: 10, expected: /Showing 21 - 23 of 23 items/ },
    ])('shows "$expected" for page $page of $totalPages ($totalItems items)', ({ page, totalPages, totalItems, pageSize, expected }) => {
      renderPagination({ currentPage: page, totalPages, totalItems, pageSize });
      expect(screen.getByText(expected)).toBeInTheDocument();
    });

    it('uses custom itemName', () => {
      renderPagination({ itemName: 'events' } as Record<string, unknown>);
      expect(screen.getByText(/of 50 events/)).toBeInTheDocument();
    });
  });

  describe('navigation buttons', () => {
    it.each([
      { name: 'First page', expectedPage: 1 },
      { name: 'Previous page', expectedPage: 2 },
      { name: 'Next page', expectedPage: 4 },
      { name: 'Last page', expectedPage: 5 },
    ])('$name calls onPageChange($expectedPage)', async ({ name, expectedPage }) => {
      const { onPageChange } = renderPagination({ currentPage: 3 });
      await user.click(screen.getByRole('button', { name }));
      expect(onPageChange).toHaveBeenCalledWith(expectedPage);
    });
  });

  describe('disabled states', () => {
    it.each([
      { page: 1, disabled: ['First page', 'Previous page'] },
      { page: 5, disabled: ['Next page', 'Last page'] },
    ])('disables $disabled on page $page', ({ page, disabled }) => {
      renderPagination({ currentPage: page });
      for (const name of disabled) {
        expect(screen.getByRole('button', { name })).toBeDisabled();
      }
    });
  });

  describe('page size selector', () => {
    it('hidden when onPageSizeChange not provided', () => {
      renderPagination();
      expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    });

    it('renders select with default options when onPageSizeChange provided', () => {
      renderPagination({ onPageSizeChange: vi.fn() } as Record<string, unknown>);
      expect(screen.getByRole('combobox')).toBeInTheDocument();
      expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual([
        '10 / page', '25 / page', '50 / page', '100 / page',
      ]);
    });

    it('fires onPageSizeChange on select change', async () => {
      const onPageSizeChange = vi.fn();
      renderPagination({ onPageSizeChange } as Record<string, unknown>);
      await user.selectOptions(screen.getByRole('combobox'), '25');
      expect(onPageSizeChange).toHaveBeenCalledWith(25);
    });
  });

  describe('visibility', () => {
    it('renders nothing when totalPages=1 and no onPageSizeChange', () => {
      const { container } = renderPagination({ totalPages: 1, totalItems: 5, pageSize: 10 });
      expect(container.querySelector('.pagination-container')).not.toBeInTheDocument();
    });

    it('still shows when totalPages=1 if onPageSizeChange present', () => {
      const { container } = renderPagination({
        totalPages: 1, totalItems: 5, pageSize: 10,
        onPageSizeChange: vi.fn(),
      } as Record<string, unknown>);
      expect(container.querySelector('.pagination-container')).toBeInTheDocument();
    });

    it('hides nav buttons when totalPages=1', () => {
      renderPagination({
        totalPages: 1, totalItems: 5, pageSize: 10,
        onPageSizeChange: vi.fn(),
      } as Record<string, unknown>);
      expect(screen.queryByRole('button', { name: 'First page' })).not.toBeInTheDocument();
    });
  });
});
