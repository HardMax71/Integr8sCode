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
        { name: 'zod', compatibilityVersion: 'mini', includeInEntry: true },
        {
            name: '@tanstack/svelte-query',
            includeInEntry: true,
            $hooks: {
                operations: {
                    // Browsing events is a read; it's a POST only because the filter goes in the body
                    getKind: (operation) =>
                        operation.method === 'post' && operation.path === '/api/v1/admin/events/browse'
                            ? ['query']
                            : undefined,
                },
            },
        },
    ],
});
