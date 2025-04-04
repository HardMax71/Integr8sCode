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

dotenv.config();
const production = !process.env.ROLLUP_WATCH;

// Create Express server directly - more reliable than rollup-plugin-serve for complex proxy scenarios
let server;

export default {
    input: 'src/main.js',
    output: {
        sourcemap: true,
        format: 'es',
        name: 'app',
        dir: 'public/build'
    },
    plugins: [
        replace({
            'process.env.VITE_BACKEND_URL': JSON.stringify(''),
            preventAssignment: true
        }),
        svelte({
            preprocess: sveltePreprocess({
                postcss: true,
            }),
            compilerOptions: {
                dev: !production
            }
        }),
        postcss({
            config: {
                path: './postcss.config.cjs'
            },
            extract: 'bundle.css',
            minimize: production,
        }),
        resolve({
            browser: true,
            dedupe: ['svelte']
        }),
        commonjs(),
        !production && {
            name: 'custom-server',
            async writeBundle() {
                // If server is already running (due to watch mode), don't start another one
                if (server) return;

                // Create an HTTPS server that we fully control
                const httpsOptions = {
                    key: fs.readFileSync('./certs/server.key'),
                    cert: fs.readFileSync('./certs/server.crt'),
                };

                server = https.createServer(httpsOptions, async (req, res) => {
                    // Add proper CORS headers for development
                    res.setHeader('Access-Control-Allow-Origin', '*');
                    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
                    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

                    // Handle preflight requests
                    if (req.method === 'OPTIONS') {
                        res.writeHead(204);
                        res.end();
                        return;
                    }

                    // API requests should be proxied to backend
                    if (req.url.startsWith('/api')) {
                        console.log(`Proxying API request: ${req.method} ${req.url}`);

                        const httpsAgent = new https.Agent({
                            ca: fs.readFileSync(path.resolve('./certs/rootCA.pem')),
                            // Keep verification enabled, but use proper agent
                            rejectUnauthorized: true
                        });

                        // Target backend options
                        const options = {
                            hostname: 'backend',
                            port: 443,
                            path: req.url,
                            method: req.method,
                            headers: {
                                ...req.headers,
                                host: 'backend',
                                // Make sure proxy doesn't cache responses
                                'cache-control': 'no-cache',
                                pragma: 'no-cache'
                            },
                            agent: httpsAgent
                        };

                        try {
                            // Create proxy request
                            const proxyReq = https.request(options, (proxyRes) => {
                                console.log(`Got backend response: ${proxyRes.statusCode} ${proxyRes.statusMessage}`);
                                console.log(`Content-Type: ${proxyRes.headers['content-type'] || 'not set'}`);

                                // Force the content type for API responses to ensure browser treats it properly
                                if (req.url.includes('/api/v1/k8s-limits')) {
                                    proxyRes.headers['content-type'] = 'application/json';
                                }

                                // Set CORS headers again to be sure
                                proxyRes.headers['access-control-allow-origin'] = '*';

                                // Copy status code and headers
                                res.writeHead(proxyRes.statusCode, proxyRes.headers);

                                // Create an array to collect response data chunks
                                const chunks = [];

                                // Collect data chunks as they come in
                                proxyRes.on('data', (chunk) => {
                                    chunks.push(chunk);
                                });

                                // When all data is received
                                proxyRes.on('end', () => {
                                    // Combine all chunks into a single buffer
                                    const data = Buffer.concat(chunks);

                                    // Log the first part of the response for debugging
                                    console.log(`Response data preview: ${data.slice(0, 100).toString()}`);

                                    // Send the response data to the client
                                    res.end(data);
                                });
                            });

                            // Handle proxy errors
                            proxyReq.on('error', (e) => {
                                console.error(`Proxy error: ${e.message}`);
                                res.writeHead(500, {'Content-Type': 'application/json'});
                                res.end(JSON.stringify({error: 'Proxy error', message: e.message}));
                            });

                            // Forward request body for methods that have one
                            if (['POST', 'PUT', 'PATCH'].includes(req.method)) {
                                req.pipe(proxyReq);
                            } else {
                                proxyReq.end();
                            }
                        } catch (err) {
                            console.error('Error in proxy:', err);
                            res.writeHead(500, {'Content-Type': 'application/json'});
                            res.end(JSON.stringify({error: 'Internal proxy error', message: err.message}));
                        }
                    }
                    // Static files - load from file system
                    else {
                        try {
                            // Normalize URL to get the file path
                            let filePath = './public' + req.url;

                            // Default to index.html for the root or directories
                            if (filePath === './public/' || filePath === './public') {
                                filePath = './public/index.html';
                            }

                            // For SPA routes without file extensions, serve index.html
                            if (!filePath.includes('.') || !fs.existsSync(filePath)) {
                                filePath = './public/index.html';
                            }

                            // Read the file
                            fs.readFile(filePath, (err, content) => {
                                if (err) {
                                    console.error(`Error reading file ${filePath}:`, err);
                                    res.writeHead(404);
                                    res.end('File not found');
                                    return;
                                }

                                // Set the content type based on file extension
                                const ext = filePath.split('.').pop();
                                const contentTypeMap = {
                                    'html': 'text/html',
                                    'js': 'text/javascript',
                                    'css': 'text/css',
                                    'json': 'application/json',
                                    'png': 'image/png',
                                    'jpg': 'image/jpeg',
                                    'svg': 'image/svg+xml',
                                };

                                const contentType = contentTypeMap[ext] || 'text/plain';
                                res.writeHead(200, {'Content-Type': contentType});
                                res.end(content);
                            });
                        } catch (err) {
                            console.error('Error serving static file:', err);
                            res.writeHead(500);
                            res.end('Server error');
                        }
                    }
                });

                // Start server
                server.listen(5001, '0.0.0.0', () => {
                    console.log('Custom HTTPS server running at https://0.0.0.0:5001');
                });

                // Properly handle shutdown
                process.on('SIGTERM', () => {
                    console.log('SIGTERM received, shutting down server');
                    server.close();
                });
            }
        },
        production && terser()
    ],
    watch: {
        clearScreen: false
    }
};