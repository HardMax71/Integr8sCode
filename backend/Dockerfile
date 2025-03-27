FROM python:3.9-slim
WORKDIR /app

# Install required packages including util-linux for shell commands.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    iputils-ping \
    curl \
    openssl \
    util-linux \
    && rm -rf /var/lib/apt/lists/*

# Install kubectl.
RUN curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
    && chmod +x kubectl && mv kubectl /usr/local/bin/

# Install Python dependencies.
# Also update setuptools to fix security vulnerabilities
RUN pip install --no-cache-dir --upgrade setuptools>=70.0.0

# Copy application files and configuration.
COPY ./app /app/app
COPY .env /app/.env
COPY openssl.cnf /app/openssl.cnf

# Ensure the certs directory exists.
RUN mkdir -p /app/certs

# CMD
CMD bash -c "\
  echo 'Waiting for certificates and kubeconfig...' && \
  while [ ! -f /app/certs/rootCA.pem ] || [ ! -f /app/kubeconfig.yaml ] || [ ! -f /app/certs/server.key ] || [ ! -f /app/certs/server.crt ]; do sleep 1; done && \
  echo 'Certificates and kubeconfig found, installing CA...' && \
  export KUBECONFIG=/app/kubeconfig.yaml && \
  cp /app/certs/rootCA.pem /usr/local/share/ca-certificates/rootCA.crt && \
  update-ca-certificates && \
  echo 'Starting application...' && \
  uvicorn app.main:app --host 0.0.0.0 --port 443 --ssl-keyfile /app/certs/server.key --ssl-certfile /app/certs/server.crt"


