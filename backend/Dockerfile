FROM python:3.12
WORKDIR /app

# Install required packages
RUN apt-get update && apt-get upgrade -y liblzma-dev liblzma5 xz-utils && \
    apt-get install -y libsnappy-dev && \
    rm -rf /var/lib/apt/lists/*

# Install kubectl (latest stable version)
RUN wget -q "https://dl.k8s.io/release/$(wget -qO- https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" -O /usr/local/bin/kubectl && \
    chmod +x /usr/local/bin/kubectl

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools>=70.0.0 wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy application files and configuration
COPY ./app /app/app
COPY ./workers /app/workers
COPY ./scripts /app/scripts
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
  PYTHONPATH=/app python /app/scripts/create_topics.py || true && \
  uvicorn app.main:app --host 0.0.0.0 --port 443 --ssl-keyfile /app/certs/server.key --ssl-certfile /app/certs/server.crt"