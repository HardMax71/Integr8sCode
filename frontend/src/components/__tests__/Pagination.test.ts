import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { user } from '#test/test-utils.ts';
import TableHarness from './TableHarness.svelte';

const things = (count: number) => Array.from({ length: count }, (_, i) => ({ id: `t${i}`, name: `thing ${i}` }));

function renderPage(rowCount: number, pageIndex = 0, pageSize = 10) {
    render(TableHarness, {
        props: { rows: things(Math.min(pageSize, rowCount)), rowCount, pagination: { pageIndex, pageSize } },
    });
}

const state = () => screen.getByTestId('pagination').textContent;
const button = (name: string) => screen.getByRole('button', { name });

describe('Pagination', () => {
    it.each([
        { rowCount: 50, pageIndex: 0, expected: 'Showing 1 - 10 of 50 things' },
        { rowCount: 50, pageIndex: 2, expected: 'Showing 21 - 30 of 50 things' },
        { rowCount: 23, pageIndex: 2, expected: 'Showing 21 - 23 of 23 things' },
    ])('shows "$expected"', ({ rowCount, pageIndex, expected }) => {
        renderPage(rowCount, pageIndex);
        expect(screen.getByText(expected)).toBeInTheDocument();
    });

    it('shows nothing when there are no rows', () => {
        renderPage(0);
        expect(screen.queryByText(/Showing/)).not.toBeInTheDocument();
        expect(screen.queryByRole('combobox', { name: 'Items per page' })).not.toBeInTheDocument();
    });

    it('shows the page size but no page buttons for a single page', () => {
        renderPage(7);
        expect(screen.getByRole('combobox', { name: 'Items per page' })).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Next page' })).not.toBeInTheDocument();
    });

    it('shows the page out of the page count', () => {
        renderPage(25, 1);
        expect(screen.getByText('2')).toBeInTheDocument();
        expect(screen.getByText('3')).toBeInTheDocument();
    });

    it.each([
        { pageIndex: 0, disabled: ['First page', 'Previous page'], enabled: ['Next page', 'Last page'] },
        { pageIndex: 2, disabled: ['Next page', 'Last page'], enabled: ['First page', 'Previous page'] },
    ])('disables $disabled on page $pageIndex', ({ pageIndex, disabled, enabled }) => {
        renderPage(25, pageIndex);
        for (const name of disabled) expect(button(name)).toBeDisabled();
        for (const name of enabled) expect(button(name)).toBeEnabled();
    });

    it.each([
        { start: 1, name: 'Next page', expected: '2/10' },
        { start: 1, name: 'Previous page', expected: '0/10' },
        { start: 1, name: 'Last page', expected: '2/10' },
        { start: 2, name: 'First page', expected: '0/10' },
    ])('$name from page $start writes pagination $expected', async ({ start, name, expected }) => {
        renderPage(25, start);
        await user.click(button(name));
        expect(state()).toBe(expected);
    });

    it('keeps the top row in view when the page size changes', async () => {
        renderPage(60, 3);
        await user.selectOptions(screen.getByRole('combobox', { name: 'Items per page' }), '25');
        await waitFor(() => expect(state()).toBe('1/25'));
    });
});
