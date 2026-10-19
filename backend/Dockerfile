# Backend image, used by the API and the worker
# The builder stage keeps gcc and the dev headers out of the final image

FROM python:3.14-slim AS builder

WORKDIR /app

# Install build-time dependencies (gcc + dev headers for C extensions)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    gcc \
    liblzma-dev \
    libsnappy-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv (using Docker Hub mirror - ghcr.io has rate limiting issues)
COPY --from=astral/uv:0.13.0 /uv /uvx /bin/

# Pre-compile bytecode for faster startup; copy mode avoids symlink issues with cache mounts
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install Python dependencies with BuildKit cache mount for faster rebuilds
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project --no-build

# Python, runtime libs and the locked dependencies; CI builds and caches this stage on its own
FROM python:3.14-slim AS base

WORKDIR /app

# Runtime libs only (no -dev headers, no gcc); uv installs the app, so pip goes too, since its vendored packages trip the scan
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
    curl \
    liblzma5 \
    libsnappy1v5 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall --yes --root-user-action=ignore pip

# Copy uv from builder (avoids second Docker Hub pull, guarantees version consistency)
COPY --from=builder /bin/uv /bin/uvx /bin/

# Copy pre-built virtual environment from builder stage
COPY --from=builder /app/.venv /app/.venv

# Copy dependency files (needed for uv to recognize the project)
COPY pyproject.toml uv.lock ./

# Set paths: PYTHONPATH for imports, PATH for venv binaries (no uv run needed at runtime)
ENV PYTHONPATH=/app
ENV PATH="/app/.venv/bin:$PATH"
# OpenTelemetry instrumentations emit the stable HTTP semantic conventions (http.server.request.duration)
ENV OTEL_SEMCONV_STABILITY_OPT_IN=http

FROM base

# Copy application files and configuration
COPY ./app /app/app
COPY ./scripts /app/scripts
COPY config.toml /app/config.toml

# Create entrypoint script inline (BuildKit heredoc)
# The users and the data fixes go in before the API serves, and the worker waits for this container's health
COPY <<'EOF' /entrypoint.sh
#!/bin/bash
set -e

python -m scripts.seed_users

echo "Starting application..."

exec gunicorn 'app.main:create_app()' \
  -k uvicorn_worker.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --workers "${WEB_CONCURRENCY:-2}" \
  --threads "${WEB_THREADS:-4}" \
  --timeout "${WEB_TIMEOUT:-60}" \
  --graceful-timeout 30 \
  --keep-alive 2 \
  --backlog 2048 \
  --log-level info \
  --access-logfile - \
  --error-logfile -
EOF

RUN chmod +x /entrypoint.sh
CMD ["/entrypoint.sh"]
