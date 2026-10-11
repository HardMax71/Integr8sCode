import { createConsola } from 'consola/browser';

export const logger = createConsola({
    level: import.meta.env.DEV ? 4 : 1,
});
