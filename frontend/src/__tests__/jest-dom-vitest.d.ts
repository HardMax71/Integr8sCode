import type { TestingLibraryMatchers } from '@testing-library/jest-dom/matchers';

// Drop once jest-dom types Vitest 5 (testing-library/jest-dom#738)
declare module 'vitest' {
    interface Matchers<R, T> extends TestingLibraryMatchers<unknown, R> {}
}
