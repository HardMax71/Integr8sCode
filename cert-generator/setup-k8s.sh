#!/bin/sh
set -e

# Set CAROOT to use the shared directory for root CA
export CAROOT=/shared_ca

# Check if a shared root CA already exists
if [ -f "$CAROOT/rootCA.pem" ] && [ -f "$CAROOT/rootCA-key.pem" ]; then
    echo "Using existing shared root CA from $CAROOT"
else
    echo "Creating new root CA in shared location $CAROOT"
    # Generate a new root CA
    mkcert -install
    # Ensure permissions allow other containers to read
    chmod 644 "$CAROOT/rootCA.pem" "$CAROOT/rootCA-key.pem"
    echo "Root CA created in $CAROOT"
fi

# Generate certificates if they don't exist
# '/certs' is the mount point specific to the container needing the certs
if [ ! -f /certs/server.crt ]; then
    echo "Generating certificates using shared root CA"
    # Generate certs valid for services and host access
    mkcert -cert-file /certs/server.crt -key-file /certs/server.key localhost backend frontend 127.0.0.1 ::1 host.docker.internal
    # Copy the root CA to the certs directory as well for easy access by services
    cp "$CAROOT/rootCA.pem" /certs/rootCA.pem
    # Ensure permissions are correct for services to read
    chmod 644 /certs/server.crt /certs/server.key /certs/rootCA.pem
    echo "Certificates generated and placed in /certs"
else
    echo "Certificates already exist in /certs"
fi

# Create a marker file to indicate completion - helps depends_on condition
touch /certs/setup-complete

echo "Certificate setup completed successfully. Exiting."