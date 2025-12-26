/**
 * Pagination state factory for admin pages
 * Provides reactive pagination state with page change handlers
 */

export interface PaginationState {
    currentPage: number;
    pageSize: number;
    totalItems: number;
    readonly totalPages: number;
    readonly skip: number;
    handlePageChange: (page: number, onLoad?: () => void) => void;
    handlePageSizeChange: (size: number, onLoad?: () => void) => void;
    reset: () => void;
}

export interface PaginationOptions {
    initialPage?: number;
    initialPageSize?: number;
    pageSizeOptions?: number[];
}

const DEFAULT_OPTIONS: Required<PaginationOptions> = {
    initialPage: 1,
    initialPageSize: 10,
    pageSizeOptions: [5, 10, 20, 50]
};

/**
 * Creates reactive pagination state
 * @example
 * const pagination = createPaginationState({ initialPageSize: 20 });
 * // Use in component:
 * // pagination.currentPage, pagination.totalPages, etc.
 */
export function createPaginationState(options: PaginationOptions = {}): PaginationState {
    const opts = { ...DEFAULT_OPTIONS, ...options };

    let currentPage = $state(opts.initialPage);
    let pageSize = $state(opts.initialPageSize);
    let totalItems = $state(0);

    const totalPages = $derived(Math.ceil(totalItems / pageSize) || 1);
    const skip = $derived((currentPage - 1) * pageSize);

    function handlePageChange(page: number, onLoad?: () => void): void {
        currentPage = page;
        onLoad?.();
    }

    function handlePageSizeChange(size: number, onLoad?: () => void): void {
        pageSize = size;
        currentPage = 1;
        onLoad?.();
    }

    function reset(): void {
        currentPage = opts.initialPage;
        pageSize = opts.initialPageSize;
        totalItems = 0;
    }

    return {
        get currentPage() { return currentPage; },
        set currentPage(v: number) { currentPage = v; },
        get pageSize() { return pageSize; },
        set pageSize(v: number) { pageSize = v; },
        get totalItems() { return totalItems; },
        set totalItems(v: number) { totalItems = v; },
        get totalPages() { return totalPages; },
        get skip() { return skip; },
        handlePageChange,
        handlePageSizeChange,
        reset
    };
}
