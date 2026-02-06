#!/bin/sh
set -e

echo "Generating certificates..."

BACKEND_CERT_DIR=${BACKEND_CERT_DIR:-/backend-certs}
FRONTEND_CERT_DIR=${FRONTEND_CERT_DIR:-/frontend-certs}

mkdir -p "$BACKEND_CERT_DIR" "$FRONTEND_CERT_DIR"
echo "BACKEND_CERT_DIR=${BACKEND_CERT_DIR}"
echo "FRONTEND_CERT_DIR=${FRONTEND_CERT_DIR}"

# Generate Self-Signed Certificate
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$BACKEND_CERT_DIR/server.key" \
  -out "$BACKEND_CERT_DIR/server.crt" \
  -subj "/CN=backend" \
  -addext "subjectAltName = DNS:backend,DNS:localhost,IP:127.0.0.1,IP:::1" \
  -days 365
echo "Created cert: $BACKEND_CERT_DIR/server.crt"
echo "Created key:  $BACKEND_CERT_DIR/server.key"
echo "Certificate fingerprint (SHA256): $(openssl x509 -in "$BACKEND_CERT_DIR/server.crt" -noout -sha256 -fingerprint | sed 's/^.*=//')"

# Copy for frontend
cp "$BACKEND_CERT_DIR/server.crt" "$FRONTEND_CERT_DIR/server.crt"
cp "$BACKEND_CERT_DIR/server.key" "$FRONTEND_CERT_DIR/server.key"
echo "Copied cert/key to frontend directory"

# Copy to shared CA directory
if [ -n "$SHARED_CA_DIR" ]; then
    cp "$BACKEND_CERT_DIR/server.crt" "$SHARED_CA_DIR/ca.pem"
    echo "Certificate copied to shared CA directory"
fi

echo "✅ Certificates generated"
