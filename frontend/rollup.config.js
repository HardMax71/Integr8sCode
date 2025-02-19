import svelte from 'rollup-plugin-svelte';
import commonjs from '@rollup/plugin-commonjs';
import resolve from '@rollup/plugin-node-resolve';
import terser from '@rollup/plugin-terser';
import postcss from 'rollup-plugin-postcss';
import sveltePreprocess from 'svelte-preprocess';
import replace from '@rollup/plugin-replace';
import dotenv from 'dotenv';
import serve from 'rollup-plugin-serve';
import fs from 'fs';

dotenv.config();
const production = !process.env.ROLLUP_WATCH;
const backendUrl = process.env.VITE_BACKEND_URL || 'https://127.0.0.1:443';

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
            'process.env.VITE_BACKEND_URL': JSON.stringify(process.env.VITE_BACKEND_URL),
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
        !production && serve({
            contentBase: ['public'],
            host: '0.0.0.0',
            port: 5001,
            https: {
                key: fs.readFileSync('./certs/server.key'),
                cert: fs.readFileSync('./certs/server.crt'),
                secure: true
            },
            historyApiFallback: true,
        }),
        //  !production && livereload('public'),
        production && terser()
    ],
    watch: {
        clearScreen: false
    }
};
