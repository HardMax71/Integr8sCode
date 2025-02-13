FROM alpine:3.17

# Install base packages and setup kubectl repository
RUN apk add --no-cache wget ca-certificates openssl curl && \
    update-ca-certificates && \
    # Install kubectl properly for Alpine
    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/arm64/kubectl" && \
    chmod +x kubectl && mv kubectl /usr/local/bin/ && \
    # Install mkcert
    wget -q https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/mkcert-v1.4.4-linux-arm64 -O /usr/local/bin/mkcert && \
    chmod +x /usr/local/bin/mkcert

COPY setup-k8s.sh /setup-k8s.sh
RUN chmod +x /setup-k8s.sh

CMD ["/setup-k8s.sh"]