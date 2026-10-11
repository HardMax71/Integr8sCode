<script lang="ts">
    import type { PaginationState } from '@tanstack/svelte-table';
    import { columnHelper, createServerTable } from '#lib/data-table.ts';
    import DataTable from '#components/DataTable.svelte';
    import Pagination from '#components/Pagination.svelte';

    interface Thing {
        id: string;
        name: string;
    }

    interface Props {
        rows: Thing[];
        rowCount: number;
        pagination?: PaginationState;
        loading?: boolean;
        cards?: boolean;
    }

    let {
        rows,
        rowCount,
        pagination = $bindable({ pageIndex: 0, pageSize: 10 }),
        loading = false,
        cards = true,
    }: Props = $props();

    const column = columnHelper<Thing>();
    const columns = [
        column.accessor('name', { header: 'Name', meta: { class: 'text-right' } }),
        column.accessor('id', { header: 'ID' }),
    ];

    const table = createServerTable(columns, {
        get rows() {
            return rows;
        },
        get rowCount() {
            return rowCount;
        },
        get pagination() {
            return pagination;
        },
        set pagination(next) {
            pagination = next;
        },
    });
</script>

<DataTable {table} label="Things" {loading} emptyText="Nothing here" {cards} />
<Pagination {table} itemName="things" pageSizeOptions={[10, 25]} />
<output data-testid="pagination">{pagination.pageIndex}/{pagination.pageSize}</output>
