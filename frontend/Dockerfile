# Build stage
FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# --8<-- [start:production_stage]
# Production stage
FROM nginx:alpine

# Install curl for healthcheck
RUN apk add --no-cache curl

# Copy built static files
COPY --from=builder /app/public /usr/share/nginx/html

# Copy nginx config template (envsubst runs at container startup)
# The nginx image automatically processes /etc/nginx/templates/*.template
# and outputs to /etc/nginx/conf.d/ with the .template suffix removed
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Create writable directories for nginx (required for read-only root filesystem)
# and certs directory for TLS certificates mounted at runtime
RUN mkdir -p /var/cache/nginx /var/run /etc/nginx/certs && \
    chown -R nginx:nginx /var/cache/nginx /var/run /etc/nginx/certs

EXPOSE 5001

CMD ["nginx", "-g", "daemon off;"]
# --8<-- [end:production_stage]
