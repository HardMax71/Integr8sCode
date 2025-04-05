FROM node:20-alpine

WORKDIR /app

# Install dependencies with ca-certificates
COPY package*.json ./
RUN npm install && apk add --no-cache openssl ca-certificates

# Copy the rest of your application
COPY . .

COPY openssl.cnf /app/openssl.cnf

EXPOSE 5001

CMD sh -c ' \
    echo "Checking for shared CA certificate at /shared_ca/rootCA.pem..."; \
    if [ -f /shared_ca/rootCA.pem ]; then \
      echo "Shared root CA certificate found, installing to system trust store..."; \
      cp /shared_ca/rootCA.pem /usr/local/share/ca-certificates/customRootCA.crt && \
      update-ca-certificates; \
      echo "System CA store updated."; \
    else \
      echo "WARNING: Shared root CA certificate not found at /shared_ca/rootCA.pem. System trust store not updated by Dockerfile CMD."; \
    fi; \
    echo "Starting development server..."; \
    # Rely on docker-compose environment for NODE_EXTRA_CA_CERTS \
    npm run dev \
'