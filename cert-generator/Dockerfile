FROM alpine:3.23

# Pin versions for reproducible builds
# kubectl: Use supported version (N-2 policy: 1.35, 1.34, 1.33 as of Feb 2026)
ARG KUBECTL_VERSION=v1.35.0

# Install required packages and tools for all architectures
RUN apk add --no-cache ca-certificates openssl curl dos2unix netcat-openbsd iproute2 && \
    update-ca-certificates && \
    # Detect architecture and install appropriate binaries
    ARCH=$(uname -m); \
    case $ARCH in \
        x86_64) KUBECTL_ARCH=amd64 ;; \
        aarch64) KUBECTL_ARCH=arm64 ;; \
        armv7l) KUBECTL_ARCH=arm ;; \
        *) echo "Unsupported architecture: $ARCH" && exit 1 ;; \
    esac && \
    # Install kubectl (pinned version for reproducibility)
    curl -fsSL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${KUBECTL_ARCH}/kubectl" -o /usr/local/bin/kubectl && \
    chmod +x /usr/local/bin/kubectl

# Create shared directory for root CA
RUN mkdir -p /shared_ca

# Copy and prepare setup scripts
COPY setup-k8s.sh /setup-k8s.sh
COPY setup-certs.sh /setup-certs.sh
RUN dos2unix /setup-k8s.sh /setup-certs.sh && chmod +x /setup-k8s.sh /setup-certs.sh

# Add a health check script for CI debugging
RUN echo '#!/bin/sh\necho "Cert Generator Health Check: OK"\n' > /health.sh && \
    chmod +x /health.sh

# Run both setup scripts (k8s setup failure must not block cert generation)
ENTRYPOINT ["/bin/sh", "-c", "/setup-k8s.sh; /setup-certs.sh"]
