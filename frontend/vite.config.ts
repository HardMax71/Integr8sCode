import fs from 'node:fs';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig, type ServerOptions } from 'vite';

// The dev server is useful inside the compose network, where the TLS certs and the backend exist
function devServer(): ServerOptions {
    const keyFile = process.env.SSL_KEY_FILE ?? './certs/server.key';
    const certFile = process.env.SSL_CERT_FILE ?? './certs/server.crt';
    const tls = fs.existsSync(keyFile) && fs.existsSync(certFile);
    return {
        host: '0.0.0.0',
        port: 5001,
        strictPort: true,
        https: tls ? { key: fs.readFileSync(keyFile), cert: fs.readFileSync(certFile) } : undefined,
        proxy: {
            '/api': { target: 'https://backend:443', secure: false },
        },
    };
}

export default defineConfig(({ command }) => ({
    plugins: [
        tailwindcss(),
        sveltekit({
            adapter: adapter({ fallback: '200.html' }),
            // --8<-- [start:csp]
            // Prerendered shells can't carry a per-request nonce, so Kit hashes its inline scripts into a meta CSP;
            // nginx adds frame-ancestors, which a meta CSP can't express
            csp: {
                mode: 'hash',
                directives: {
                    'default-src': ['self'],
                    'script-src': ['self'],
                    'style-src-elem': ['self', 'https://fonts.googleapis.com'],
                    'style-src-attr': ['unsafe-inline'],
                    'img-src': ['self', 'data:', 'blob:'],
                    'font-src': ['self', 'data:', 'https://fonts.gstatic.com'],
                    'connect-src': ['self'],
                    'object-src': ['none'],
                    'base-uri': ['self'],
                    'form-action': ['self'],
                },
            },
            // --8<-- [end:csp]
        }),
    ],
    server: command === 'serve' && !process.env.VITEST ? devServer() : undefined,
}));
