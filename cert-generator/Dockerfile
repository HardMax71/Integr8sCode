FROM alpine:3.17

# Install required packages and tools for all architectures
RUN apk add --no-cache wget ca-certificates openssl curl dos2unix && \
    update-ca-certificates && \
    # Detect architecture and install appropriate binaries
    ARCH=$(uname -m); \
    case $ARCH in \
        x86_64) KUBECTL_ARCH=amd64; MKCERT_ARCH=amd64 ;; \
        aarch64) KUBECTL_ARCH=arm64; MKCERT_ARCH=arm64 ;; \
        armv7l) KUBECTL_ARCH=arm; MKCERT_ARCH=arm ;; \
        *) echo "Unsupported architecture: $ARCH" && exit 1 ;; \
    esac && \
    # Install kubectl
    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/${KUBECTL_ARCH}/kubectl" && \
    chmod +x kubectl && \
    mv kubectl /usr/local/bin/ && \
    # Install mkcert
    wget -q "https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/mkcert-v1.4.4-linux-${MKCERT_ARCH}" -O /usr/local/bin/mkcert && \
    chmod +x /usr/local/bin/mkcert

# Copy and prepare setup script
COPY setup-k8s.sh /setup-k8s.sh
RUN dos2unix /setup-k8s.sh && chmod +x /setup-k8s.sh

ENTRYPOINT ["/bin/sh", "-c", "/setup-k8s.sh"]