FROM python:3.9-slim

WORKDIR /app

# Update apt-get and install required packages including curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    iputils-ping \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app /app/app
COPY .env /app/.env
COPY kubeconfig.yaml /app/kubeconfig.yaml
COPY certs /app/certs

RUN cp /app/certs/ca.crt /usr/local/share/ca-certificates/integr8scode-ca.crt && update-ca-certificates

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "443", "--ssl-keyfile", "/app/certs/server.key", "--ssl-certfile", "/app/certs/server.crt"]
