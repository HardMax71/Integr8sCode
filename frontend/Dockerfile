FROM node:22-slim

WORKDIR /app

# Install curl for healthcheck (not included in slim image)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy lockfile for reproducible, faster installs
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

COPY openssl.cnf /app/openssl.cnf

EXPOSE 5001

CMD ["npm", "run", "dev"]