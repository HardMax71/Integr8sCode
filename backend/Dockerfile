FROM python:3.9
WORKDIR /app

# Install required packages including util-linux for shell commands.
RUN apt-get update && apt-get upgrade -y liblzma-dev liblzma5 xz-utils && \
    rm -rf /var/lib/apt/lists/*

# Install kubectl.
RUN curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
    && chmod +x kubectl && mv kubectl /usr/local/bin/

# Install Python dependencies.
# Also update setuptools to fix security vulnerabilities
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools>=70.0.0 wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy application files and configuration.
COPY ./app /app/app
COPY .env /app/.env
COPY openssl.cnf /app/openssl.cnf

# Ensure the certs directory exists.
RUN mkdir -p /app/certs

# CMD with improved error handling and logging
CMD bash -c "\
  echo 'Waiting for certificates...' && \
  while [ ! -f /app/certs/rootCA.pem ] || [ ! -f /app/certs/server.key ] || [ ! -f /app/certs/server.crt ]; do \
    echo 'Still waiting for certificates...'; \
    ls -la /app/certs || echo 'Cannot list cert directory'; \
    sleep 2; \
  done && \
  echo 'Certificates found, installing CA...' && \
  cp /app/certs/rootCA.pem /usr/local/share/ca-certificates/rootCA.crt && \
  update-ca-certificates && \
  \
  # Wait for kubeconfig.yaml with better error handling \
  echo 'Checking for kubeconfig.yaml...' && \
  WAIT_COUNT=0 && \
  while [ ! -f /app/kubeconfig.yaml ] && [ $WAIT_COUNT -lt 30 ]; do \
    echo 'Waiting for kubeconfig.yaml... attempt '$WAIT_COUNT; \
    ls -la /app || echo 'Cannot list app directory'; \
    WAIT_COUNT=$((WAIT_COUNT+1)); \
    sleep 2; \
  done && \
  \
  if [ -f /app/kubeconfig.yaml ]; then \
    echo 'kubeconfig.yaml found, setting KUBECONFIG environment variable' && \
    export KUBECONFIG=/app/kubeconfig.yaml && \
    echo 'Verifying kubectl connection...' && \
    (kubectl version --client || echo 'kubectl client check completed with warnings') && \
    (kubectl get pods --request-timeout=5s || echo 'kubectl server check failed, proceeding anyway...'); \
  else \
    echo 'WARNING: kubeconfig.yaml not found after timeout, K8s features may not work'; \
  fi && \
  \
  echo 'Starting application...' && \
  uvicorn app.main:app --host 0.0.0.0 --port 443 --ssl-keyfile /app/certs/server.key --ssl-certfile /app/certs/server.crt"