FROM node:22-slim

WORKDIR /app

# Copy lockfile for reproducible, faster installs
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

COPY openssl.cnf /app/openssl.cnf

EXPOSE 5001

CMD ["npm", "run", "dev"]