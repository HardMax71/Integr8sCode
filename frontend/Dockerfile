FROM node:20-alpine

WORKDIR /app

# Install dependencies with ca-certificates
COPY package*.json ./
RUN npm install && apk add --no-cache openssl ca-certificates

# Copy the rest of your application
COPY . .

# Copy the OpenSSL config file
COPY openssl.cnf /app/openssl.cnf

EXPOSE 5001

CMD sh -c 'if [ ! -f /app/certs/server.crt ]; then \
             echo "Certificate not found, generating one..."; \
             mkdir -p /app/certs && \
             openssl req -x509 -nodes -days 365 -newkey rsa:4096 \
               -keyout /app/certs/server.key \
               -out /app/certs/server.crt \
               -config /app/openssl.cnf \
             chmod 644 /app/certs/server.key /app/certs/server.crt; \
           fi && \
           if [ -f /app/certs/rootCA.pem ]; then \
             echo "Installing root CA certificate..."; \
             mkdir -p /usr/local/share/ca-certificates && \
             cp /app/certs/rootCA.pem /usr/local/share/ca-certificates/rootCA.crt && \
             update-ca-certificates && \
             # Set NODE_EXTRA_CA_CERTS for Node.js to trust the CA \
             export NODE_EXTRA_CA_CERTS=/app/certs/rootCA.pem; \
           fi && \
           npm run dev'