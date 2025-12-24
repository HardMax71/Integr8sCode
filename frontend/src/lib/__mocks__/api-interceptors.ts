import { vi } from 'vitest';

// Only mock the function that has side effects (sets up HTTP interceptors)
export const initializeApiInterceptors = vi.fn();

// Re-export real pure functions - no need to mock these
export { getErrorMessage, unwrap, unwrapOr } from '../api-interceptors';
