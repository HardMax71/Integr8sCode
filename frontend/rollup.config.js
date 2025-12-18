import svelte from 'rollup-plugin-svelte';
import commonjs from '@rollup/plugin-commonjs';
import resolve from '@rollup/plugin-node-resolve';
import terser from '@rollup/plugin-terser';
import postcss from 'rollup-plugin-postcss';
import sveltePreprocess from 'svelte-preprocess';
import replace from '@rollup/plugin-replace';
import dotenv from 'dotenv';
import fs from 'fs';
import https from 'https';
import path from 'path';
import json from '@rollup/plugin-json';

dotenv.config();
const production = !process.env.ROLLUP_WATCH;

let server;

// Helper function to start the dev server
function startServer() {
    if (server) return;

    // --- HTTPS options for the DEV server itself ---
    const httpsOptions = {
        key: fs.readFileSync(process.env.SSL_KEY_FILE || './certs/server.key'),
        cert: fs.readFileSync(process.env.SSL_CERT_FILE || './certs/server.crt'),
    };

    // --- HTTPS Agent for the PROXY to the backend ---
    const caPath = '/shared_ca/mkcert-ca.pem';
    if (!fs.existsSync(caPath)) {
        console.error(`\n\nFATAL ERROR: The CA certificate for the proxy is missing.`);
        console.error(`Expected path: ${caPath}`);
        console.error(`Make sure cert-generator has run successfully.\n\n`);
        process.exit(1); // Exit if the CA is missing.
    }

    const proxyAgent = new https.Agent({
        ca: fs.readFileSync(caPath),
        rejectUnauthorized: false  // Accept self-signed certificates in development
    });

    server = https.createServer(httpsOptions, (req, res) => {
        // Proxy API requests
        if (req.url.startsWith('/api')) {
            // Forward the original host header and cookies
            const proxyHeaders = { ...req.headers };
            proxyHeaders.host = req.headers.host || 'localhost:5001';
            
            const options = {
                hostname: 'backend',
                port: 443,
                path: req.url,
                method: req.method,
                headers: proxyHeaders,
                agent: proxyAgent // Use our special agent that trusts our CA
            };

            const proxyReq = https.request(options, (proxyRes) => {
                res.writeHead(proxyRes.statusCode, proxyRes.headers);
                proxyRes.pipe(res, { end: true });
            });

            proxyReq.on('error', (e) => {
                console.error(`Proxy request error: ${e.message}`);
                res.writeHead(502);
                res.end('Bad Gateway');
            });

            req.pipe(proxyReq, { end: true });

        } else {
            // Serve static files
            let filePath = './public' + req.url;
            if (filePath === './public/') filePath = './public/index.html';

            const extname = String(path.extname(filePath)).toLowerCase();
            const mimeTypes = {
                '.html': 'text/html',
                '.js': 'text/javascript',
                '.css': 'text/css',
                '.json': 'application/json',
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.svg': 'image/svg+xml',
            };
            const contentType = mimeTypes[extname] || 'application/octet-stream';

            fs.readFile(filePath, (error, content) => {
                if (error) {
                    if(error.code == 'ENOENT') {
                        // If file not found, serve index.html for SPA routing
                        fs.readFile('./public/index.html', (err, cont) => {
                            res.writeHead(200, { 'Content-Type': 'text/html' });
                            res.end(cont, 'utf-8');
                        });
                    } else {
                        res.writeHead(500);
                        res.end('Sorry, check with the site admin for error: '+error.code+' ..\n');
                    }
                } else {
                    res.writeHead(200, { 'Content-Type': contentType });
                    res.end(content, 'utf-8');
                }
            });
        }
    });

    server.listen(5001, '0.0.0.0', () => {
        console.log('✅ Custom HTTPS dev server running at https://localhost:5001');
    });
}

export default {
    input: 'src/main.js',
    output: {
        sourcemap: true,
        format: 'es',
        name: 'app',
        dir: 'public/build',
        manualChunks: {
            'vendor': [
                'svelte',
                'svelte-routing',
                'axios'
            ],
            'codemirror': [
                '@codemirror/state',
                '@codemirror/view',
                '@codemirror/commands',
                '@codemirror/language',
                '@codemirror/autocomplete',
                '@codemirror/lang-python',
                '@codemirror/theme-one-dark',
                '@uiw/codemirror-theme-github'
            ]
        },
        generatedCode: {
            arrowFunctions: true,
            constBindings: true,
            objectShorthand: true
        }
    },
    plugins: [
        replace({
            'process.env.VITE_BACKEND_URL': JSON.stringify(''),
            preventAssignment: true
        }),
        svelte({
            preprocess: sveltePreprocess({ postcss: true }),
            compilerOptions: { dev: !production }
        }),
        postcss({
            extract: 'bundle.css',
            minimize: production,
        }),
        json(),
        resolve({
            browser: true,
            dedupe: ['svelte'],
            preferBuiltins: false,
            // Prefer ES modules
            mainFields: ['svelte', 'module', 'browser', 'main'],
            exportConditions: ['svelte']
        }),
        commonjs(),
        !production && {
            name: 'custom-server',
            writeBundle() {
                startServer();
            }
        },
        production && terser({
            ecma: 2020,
            module: true,
            compress: {
                passes: 2,
                drop_console: true
            },
            format: {
                comments: false
            }
        })
    ],
    watch: {
        clearScreen: false
    }
};