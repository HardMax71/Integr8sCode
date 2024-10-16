# Setting up HTTPS with SSL/TLS for Frontend and Backend

This guide provides step-by-step instructions to set up HTTPS with SSL/TLS for both the frontend (Svelte) and backend (FastAPI) of your application.

## Prerequisites

- Docker and Docker Compose installed
- Node.js and npm installed
- OpenSSL installed
- A Mac M1 computer (adjust commands if using a different system)

> Start folder: the one with /backend and /frontend folders

## Backend Setup

1. Generate SSL certificates for the backend:

```bash
cd /backend
mkdir certs
openssl req -x509 -newkey rsa:4096 -nodes -keyout certs/server.key -out certs/server.crt -days 365 -subj "/CN=localhost"
```

2. Extract the Kubernetes cluster CA certificate:

```bash
kubectl config view --raw -o jsonpath="{.clusters[?(@.name=='docker-desktop')].cluster.certificate-authority-data}" | base64 --decode > certs/ca.crt
```

3. Ensure the CA certificate ends with a newline:

```bash
echo >> certs/ca.crt
```

4. Update your Dockerfile for backend:

```Dockerfile
FROM python:3.9-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    iputils-ping \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app /app/app
COPY .env /app/.env
COPY kubeconfig.yaml /app/kubeconfig.yaml
COPY certs /app/certs

RUN cp /app/certs/ca.crt /usr/local/share/ca-certificates/integr8scode-ca.crt && update-ca-certificates

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "443", "--ssl-keyfile", "/app/certs/server.key", "--ssl-certfile", "/app/certs/server.crt"]
```

5. Update your docker-compose.yml (backend):

```docker-compose
services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "443:443"
    depends_on:
      - mongo
    volumes:
      - ./kubeconfig.yaml:/app/kubeconfig.yaml:ro
      - ./certs:/app/certs:ro
    networks:
      - app-network

  mongo:
    image: mongo:4.4
    ports:
      - "27017:27017"
    volumes:
      - mongo_data:/data/db
    networks:
      - app-network

volumes:
  mongo_data:

networks:
  app-network:
    driver: bridge
```

6. Update main.py to use HTTPS:

```python
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=443, ssl_keyfile="/app/certs/server.key", ssl_certfile="/app/certs/server.crt")
```

7. Update CORS settings in main.py:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://localhost:5001", # :5000 is taken by the backend
        "https://127.0.0.1:5001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)
```

8. Rebuild and restart your Docker containers:

```bash
docker-compose build
docker-compose down
docker-compose up
```

## Frontend Setup

1. Generate SSL certificates for the frontend:

```bash
cd /frontend
mkdir certs
openssl req -x509 -newkey rsa:4096 -nodes -keyout certs/server.key -out certs/server.crt -days 365 -subj "/CN=localhost"
```

2. Install necessary packages:

```bash
npm install --save-dev rollup-plugin-serve express
```

> AFAIK already inside package.json

3. Update your rollup.config.js:

```javascript
import svelte from 'rollup-plugin-svelte';
import commonjs from '@rollup/plugin-commonjs';
import resolve from '@rollup/plugin-node-resolve';
import livereload from 'rollup-plugin-livereload';
import terser from '@rollup/plugin-terser';
import postcss from 'rollup-plugin-postcss';
import sveltePreprocess from 'svelte-preprocess';
import replace from '@rollup/plugin-replace';
import dotenv from 'dotenv';
import serve from 'rollup-plugin-serve';
import fs from 'fs';

dotenv.config();
const production = !process.env.ROLLUP_WATCH;

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
            host: 'localhost',
            port: 5001,
            headers: {
                'Access-Control-Allow-Origin': '*'
            },
            https: {
                key: fs.readFileSync('./certs/server.key'),
                cert: fs.readFileSync('./certs/server.crt')
            }
        }),
        !production && livereload('public'),
        production && terser()
    ],
    watch: {
        clearScreen: false
    }
};
```

4. Update .env file (frontend):

```env
VITE_BACKEND_URL=https://localhost
```
5. Start your frontend development server:

```bash
npm run dev
```

## Testing the Setup

1. Access frontend at https://localhost:5001

2. Accept the self-signed certificate warning in your browser

3. Your frontend should now be able to communicate with your backend over HTTPS

## Troubleshooting

- If you encounter SSL errors, ensure that your CA certificates are correct and accessible to your application.
- Verify that the hostnames in your certificates match the ones you're using (e.g., localhost, kubernetes.docker.internal).
- Check that your Docker containers have the correct certificates mounted and accessible.
- Use curl inside your Docker container (`backend-app-1`) to test connectivity:

```bash
ping -c 3 kubernetes.docker.internal
curl -vk https://kubernetes.docker.internal:6443
```

> `backend-app-1` is default name of container with FastAPI backend inside.

- If you're still having issues, check your application logs for more detailed error messages.

Remember to replace self-signed certificates with proper ones from a trusted Certificate Authority for production use.