import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
    input: '../docs/reference/openapi.json',
    output: {
        path: 'src/lib/api',
    },
    postProcess: ['prettier'],
    plugins: [
        { name: '@hey-api/typescript', enums: 'javascript' },
        '@hey-api/sdk',
        { name: '@hey-api/client-fetch', includeInEntry: true },
        { name: 'zod', includeInEntry: true },
    ],
});
