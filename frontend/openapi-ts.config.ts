import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
    input: '../docs/reference/openapi.json',
    output: {
        path: 'src/lib/api',
        format: 'prettier',
    },
    plugins: [
        '@hey-api/typescript',
        '@hey-api/sdk',
        '@hey-api/client-fetch',
    ],
});
