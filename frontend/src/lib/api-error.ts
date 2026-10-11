/** A request that got an error response, or no response at all, in which case `status` is undefined. */
export class ApiError extends Error {
    constructor(
        readonly status: number | undefined,
        readonly body: unknown,
    ) {
        super(status === undefined ? 'Network error' : `HTTP ${status}`);
        this.name = 'ApiError';
    }
}
