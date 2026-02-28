import { describe, it, expect, vi } from 'vitest';

const { createPaginationState } = await import('../pagination.svelte');

describe('createPaginationState', () => {
    describe('defaults', () => {
        it('initialises with default values', () => {
            const p = createPaginationState();
            expect(p.currentPage).toBe(1);
            expect(p.pageSize).toBe(10);
            expect(p.totalItems).toBe(0);
            expect(p.totalPages).toBe(1);
            expect(p.skip).toBe(0);
        });
    });

    describe('custom options', () => {
        it.each([
            [{ initialPage: 3, initialPageSize: 20 }, 3, 20],
            [{ initialPage: 1, initialPageSize: 5 }, 1, 5],
        ])('createPaginationState(%j) → page=%d, size=%d', (opts, page, size) => {
            const p = createPaginationState(opts);
            expect(p.currentPage).toBe(page);
            expect(p.pageSize).toBe(size);
        });
    });

    describe('totalPages', () => {
        it.each([
            [0, 10, 1],    // empty → 1 page
            [5, 10, 1],    // fewer than page size
            [10, 10, 1],   // exactly one page
            [11, 10, 2],   // one extra item
            [100, 20, 5],  // even split
            [101, 20, 6],  // one extra
        ])('totalItems=%d, pageSize=%d → totalPages=%d', (items, size, expected) => {
            const p = createPaginationState({ initialPageSize: size });
            p.totalItems = items;
            expect(p.totalPages).toBe(expected);
        });
    });

    describe('skip', () => {
        it.each([
            [1, 10, 0],
            [2, 10, 10],
            [3, 20, 40],
            [5, 5, 20],
        ])('page=%d, size=%d → skip=%d', (page, size, expected) => {
            const p = createPaginationState({ initialPage: page, initialPageSize: size });
            expect(p.skip).toBe(expected);
        });
    });

    describe('handlePageChange', () => {
        it('updates currentPage and calls onLoad', () => {
            const p = createPaginationState();
            const onLoad = vi.fn();
            p.handlePageChange(5, onLoad);
            expect(p.currentPage).toBe(5);
            expect(onLoad).toHaveBeenCalledOnce();
        });

        it('works without onLoad callback', () => {
            const p = createPaginationState();
            p.handlePageChange(3);
            expect(p.currentPage).toBe(3);
        });
    });

    describe('handlePageSizeChange', () => {
        it('updates pageSize, resets to page 1, and calls onLoad', () => {
            const p = createPaginationState({ initialPage: 5 });
            const onLoad = vi.fn();
            p.handlePageSizeChange(50, onLoad);
            expect(p.pageSize).toBe(50);
            expect(p.currentPage).toBe(1);
            expect(onLoad).toHaveBeenCalledOnce();
        });
    });

});
