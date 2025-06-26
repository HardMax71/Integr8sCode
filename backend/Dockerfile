FROM python:3.9
WORKDIR /app

# Install required packages
RUN apt-get update && apt-get upgrade -y liblzma-dev liblzma5 xz-utils && \
    rm -rf /var/lib/apt/lists/*

# Install kubectl
RUN curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
    && chmod +x kubectl && mv kubectl /usr/local/bin/

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools>=70.0.0 wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy application files and configuration
COPY ./app /app/app
COPY .env /app/.env
COPY openssl.cnf /app/openssl.cnf

# Ensure the certs directory exists
RUN mkdir -p /app/certs

# Simplified CMD
CMD bash -c "\
  while [ ! -f /app/certs/server.key ]; do echo 'Waiting for certs...'; sleep 2; done && \
  while [ ! -f /app/kubeconfig.yaml ]; do echo 'Waiting for kubeconfig...'; sleep 2; done && \
  echo 'Certs and kubeconfig found. Starting application...' && \
  export KUBECONFIG=/app/kubeconfig.yaml && \
  uvicorn app.main:app --host 0.0.0.0 --port 443 --ssl-keyfile /app/certs/server.key --ssl-certfile /app/certs/server.crt"