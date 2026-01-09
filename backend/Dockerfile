# Backend API service
FROM base

# Copy application files and configuration
COPY ./app /app/app
COPY ./workers /app/workers
COPY ./scripts /app/scripts
COPY .env /app/.env
COPY openssl.cnf /app/openssl.cnf

# Ensure the certs directory exists
RUN mkdir -p /app/certs

# Expose metrics port
EXPOSE 9090

# Create entrypoint script inline (BuildKit heredoc)
COPY <<'EOF' /entrypoint.sh
#!/bin/bash
set -e

while [ ! -f /app/certs/server.key ]; do
  echo "Waiting for TLS certs..."
  sleep 2
done

echo "Starting application..."
[ -f /app/kubeconfig.yaml ] && export KUBECONFIG=/app/kubeconfig.yaml

exec gunicorn 'app.main:create_app' \
  --factory \
  -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:443 \
  --workers ${WEB_CONCURRENCY:-4} \
  --threads ${WEB_THREADS:-1} \
  --timeout ${WEB_TIMEOUT:-60} \
  --graceful-timeout 30 \
  --keep-alive 2 \
  --backlog ${WEB_BACKLOG:-2048} \
  --log-level info \
  --access-logfile - \
  --error-logfile - \
  --keyfile /app/certs/server.key \
  --certfile /app/certs/server.crt
EOF

RUN chmod +x /entrypoint.sh
CMD ["/entrypoint.sh"]
