import { createConsola } from 'consola/browser';

const isProduction = false;

export const logger = createConsola({
    // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition -- replaced by Rollup at build time
    level: isProduction ? 1 : 4,
});
