# Backend API service
FROM base

# Copy application files and configuration
COPY ./app /app/app
COPY ./workers /app/workers
COPY ./scripts /app/scripts
COPY config.toml /app/config.toml
COPY openssl.cnf /app/openssl.cnf

# Ensure the certs directory exists
RUN mkdir -p /app/certs

# Expose metrics port
EXPOSE 9090

# Create entrypoint script inline (BuildKit heredoc)
# Note: cert wait is handled by docker-compose depends_on (cert-generator: service_completed_successfully)
COPY <<'EOF' /entrypoint.sh
#!/bin/bash
set -e

echo "Starting application..."

exec gunicorn 'app.main:create_app()' \
  -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:443 \
  --workers "${WEB_CONCURRENCY:-2}" \
  --threads "${WEB_THREADS:-4}" \
  --timeout "${WEB_TIMEOUT:-60}" \
  --graceful-timeout 30 \
  --keep-alive 2 \
  --backlog 2048 \
  --log-level info \
  --access-logfile - \
  --error-logfile - \
  --keyfile /app/certs/server.key \
  --certfile /app/certs/server.crt
EOF

RUN chmod +x /entrypoint.sh
CMD ["/entrypoint.sh"]
