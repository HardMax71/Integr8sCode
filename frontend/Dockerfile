FROM node:16-alpine

WORKDIR /app

# Install dependencies and openssl
COPY package*.json ./
RUN npm install && apk add --no-cache openssl

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
           fi && npm run dev'


