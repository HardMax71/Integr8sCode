import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/svelte';
import TableHarness from './TableHarness.svelte';

const things = [
    { id: 't1', name: 'first' },
    { id: 't2', name: 'second' },
];

describe('DataTable', () => {
    it('renders a header per column and a row per item', () => {
        render(TableHarness, { props: { rows: things, rowCount: 2 } });
        const table = within(screen.getByRole('table', { name: 'Things' }));

        expect(table.getAllByRole('columnheader').map((th) => th.textContent?.trim())).toEqual(['Name', 'ID']);
        expect(table.getAllByRole('row')).toHaveLength(3);
        expect(table.getByRole('cell', { name: 'second' })).toBeInTheDocument();
    });

    it('puts the column meta class on its header and cells', () => {
        render(TableHarness, { props: { rows: things, rowCount: 2 } });
        const table = within(screen.getByRole('table', { name: 'Things' }));

        expect(table.getByRole('columnheader', { name: 'Name' })).toHaveClass('text-right');
        expect(table.getByRole('cell', { name: 'first' })).toHaveClass('text-right');
        expect(table.getByRole('cell', { name: 't1' })).not.toHaveClass('text-right');
    });

    it('renders a card per item, labelled by the column headers', () => {
        render(TableHarness, { props: { rows: things, rowCount: 2 } });
        const cards = within(screen.getByRole('list', { name: 'Things' })).getAllByRole('listitem');

        expect(cards).toHaveLength(2);
        expect(within(cards[0]!).getByText('Name')).toBeInTheDocument();
        expect(within(cards[0]!).getByText('first')).toBeInTheDocument();
    });

    it('leaves the cards out when asked to', () => {
        render(TableHarness, { props: { rows: things, rowCount: 2, cards: false } });
        expect(screen.queryByRole('list', { name: 'Things' })).not.toBeInTheDocument();
        expect(screen.getByRole('table', { name: 'Things' })).toBeInTheDocument();
    });

    it('shows the loading text while the first page loads', () => {
        render(TableHarness, { props: { rows: [], rowCount: 0, loading: true } });
        expect(screen.getByText('Loading things...')).toBeInTheDocument();
        expect(screen.queryByRole('table')).not.toBeInTheDocument();
    });

    it('keeps showing the rows while a later page loads', () => {
        render(TableHarness, { props: { rows: things, rowCount: 2, loading: true } });
        expect(screen.queryByText('Loading things...')).not.toBeInTheDocument();
        expect(screen.getByRole('table', { name: 'Things' })).toBeInTheDocument();
    });

    it('shows the empty text when there are no rows', () => {
        render(TableHarness, { props: { rows: [], rowCount: 0 } });
        expect(screen.getByText('Nothing here')).toBeInTheDocument();
    });
});
