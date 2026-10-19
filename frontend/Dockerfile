# Build stage
FROM node:26-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts

COPY . .
RUN npm run build

# --8<-- [start:production_stage]
# Production stage
FROM nginx:1.31-alpine AS production

# Upgrade the base image's packages to pick up fixes newer than the image, and add curl for the healthcheck and openssl for the certificate
RUN apk upgrade --no-cache && apk add --no-cache curl openssl

# Copy built static files
COPY --from=builder /app/build /usr/share/nginx/html

# Copy nginx config template (envsubst runs at container startup)
# The nginx image automatically processes /etc/nginx/templates/*.template
# and outputs to /etc/nginx/conf.d/ with the .template suffix removed
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
ENV GRAFANA_PUBLIC_URL=http://localhost:3000/

# Create writable directories for nginx (required for read-only root filesystem)
# and certs directory for TLS certificates
RUN mkdir -p /var/cache/nginx /var/run /etc/nginx/certs && \
    chown -R nginx:nginx /var/cache/nginx /var/run /etc/nginx/certs

# nginx's entrypoint runs this before it starts; a certificate mounted at /etc/nginx/certs is kept as is
COPY --chmod=755 <<'EOF' /docker-entrypoint.d/05-self-signed-cert.sh
#!/bin/sh
set -e
if [ -s /etc/nginx/certs/server.crt ]; then
    exit 0
fi
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -quiet -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1" \
    -keyout /etc/nginx/certs/server.key -out /etc/nginx/certs/server.crt
EOF

EXPOSE 5001

CMD ["nginx", "-g", "daemon off;"]
# --8<-- [end:production_stage]
