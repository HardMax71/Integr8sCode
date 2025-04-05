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
            'process.env.VITE_BACKEND_URL': JSON.stringify(''), // Keep this if needed elsewhere, proxy uses direct URL now
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

                const caPath = process.env.NODE_EXTRA_CA_CERTS;
                if (!caPath) {
                    console.error("ERROR: NODE_EXTRA_CA_CERTS environment variable is not set!");
                } else if (!fs.existsSync(caPath)) {
                     console.error(`ERROR: CA certificate file not found at path specified by NODE_EXTRA_CA_CERTS: ${caPath}`);
                }
                console.log(`Using CA certificate for proxy agent from: ${caPath || 'Not Set'}`);

                const httpsOptions = {
                    key: fs.readFileSync(process.env.SSL_KEY_FILE || './certs/server.key'),
                    cert: fs.readFileSync(process.env.SSL_CERT_FILE || './certs/server.crt'),
                };

                server = https.createServer(httpsOptions, async (req, res) => {
                    res.setHeader('Access-Control-Allow-Origin', '*');
                    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
                    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

                    if (req.method === 'OPTIONS') {
                        res.writeHead(204);
                        res.end();
                        return;
                    }

                    if (req.url.startsWith('/api')) {
                        console.log(`Proxying API request: ${req.method} ${req.url}`);

                        const agentOptions = {
                             rejectUnauthorized: true
                        };
                        if (caPath && fs.existsSync(caPath)) {
                             agentOptions.ca = fs.readFileSync(caPath);
                        } else {
                             console.warn("WARNING: Proceeding with proxy agent WITHOUT custom CA certificate.");
                        }
                        const httpsAgent = new https.Agent(agentOptions);

                        const options = {
                            hostname: 'backend',
                            port: 443,
                            path: req.url,
                            method: req.method,
                            headers: {
                                ...req.headers,
                                host: 'backend',
                                'cache-control': 'no-cache',
                                pragma: 'no-cache'
                            },
                            agent: httpsAgent
                        };

                        try {
                            const proxyReq = https.request(options, (proxyRes) => {
                                console.log(`Got backend response: ${proxyRes.statusCode} ${proxyRes.statusMessage}`);
                                console.log(`Content-Type: ${proxyRes.headers['content-type'] || 'not set'}`);

                                if (req.url.includes('/api/v1/k8s-limits')) {
                                    proxyRes.headers['content-type'] = 'application/json';
                                }

                                proxyRes.headers['access-control-allow-origin'] = '*';

                                res.writeHead(proxyRes.statusCode, proxyRes.headers);

                                const chunks = [];
                                proxyRes.on('data', (chunk) => {
                                    chunks.push(chunk);
                                });
                                proxyRes.on('end', () => {
                                    const data = Buffer.concat(chunks);
                                    console.log(`Response data preview: ${data.slice(0, 100).toString()}`);
                                    res.end(data);
                                });
                            });

                            proxyReq.on('error', (e) => {
                                console.error(`Proxy error connecting to backend: ${e.message}`);
                                if (e.code === 'UNABLE_TO_VERIFY_LEAF_SIGNATURE' || e.code === 'CERT_HAS_EXPIRED' ) {
                                     console.error("Certificate verification failed. Check backend cert and frontend CA.");
                                }
                                res.writeHead(502, {'Content-Type': 'application/json'});
                                res.end(JSON.stringify({error: 'Proxy connection error', message: e.message}));
                            });

                            if (['POST', 'PUT', 'PATCH'].includes(req.method)) {
                                req.pipe(proxyReq);
                            } else {
                                proxyReq.end();
                            }
                        } catch (err) {
                            console.error('Error initiating proxy request:', err);
                            res.writeHead(500, {'Content-Type': 'application/json'});
                            res.end(JSON.stringify({error: 'Internal proxy setup error', message: err.message}));
                        }
                    }
                    else {
                        try {
                            let filePath = './public' + req.url;
                            if (filePath === './public/' || filePath === './public') {
                                filePath = './public/index.html';
                            }
                            if (!filePath.includes('.') || !fs.existsSync(filePath)) {
                                filePath = './public/index.html';
                            }

                            fs.readFile(filePath, (err, content) => {
                                if (err) {
                                    console.error(`Error reading file ${filePath}:`, err);
                                    res.writeHead(404);
                                    res.end('File not found');
                                    return;
                                }

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

                server.listen(5001, '0.0.0.0', () => {
                    console.log('Custom HTTPS server running at https://0.0.0.0:5001');
                });

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