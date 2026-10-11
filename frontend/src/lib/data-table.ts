import {
    createColumnHelper,
    createTable,
    functionalUpdate,
    rowPaginationFeature,
    tableFeatures,
    type CellData,
    type ColumnDef,
    type ColumnHelper,
    type PaginationState,
    type RowData,
    type Table,
    type TableFeatures,
} from '@tanstack/svelte-table';

declare module '@tanstack/table-core' {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    interface ColumnMeta<
        in out TFeatures extends TableFeatures,
        in out TData extends RowData,
        TValue extends CellData = CellData,
    > {
        /** Extra classes for the column's header and cells */
        class?: string;
    }
}

export const features = tableFeatures({ rowPaginationFeature });

export type AppTable<TData extends RowData> = Table<typeof features, TData>;
export type AppColumn<TData extends RowData> = ColumnDef<typeof features, TData, any>;

export function columnHelper<TData extends RowData>(): ColumnHelper<typeof features, TData> {
    return createColumnHelper<typeof features, TData>();
}

export interface ServerPage<TData> {
    readonly rows: TData[];
    readonly rowCount: number;
    pagination: PaginationState;
}

/** A table over the one page the server sent; paging writes `source.pagination`, which the query reads. */
export function createServerTable<TData extends RowData>(
    columns: AppColumn<TData>[],
    source: ServerPage<TData>,
): AppTable<TData> {
    return createTable({
        features,
        columns,
        get data() {
            return source.rows;
        },
        get rowCount() {
            return source.rowCount;
        },
        manualPagination: true,
        state: {
            get pagination() {
                return source.pagination;
            },
        },
        onPaginationChange: (updater) => {
            source.pagination = functionalUpdate(updater, source.pagination);
        },
    });
}
