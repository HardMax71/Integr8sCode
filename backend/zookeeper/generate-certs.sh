#!/bin/sh
set -e

# Check if certificates already exist
if [ -f /certs/zookeeper.keystore.jks ] && [ -f /certs/zookeeper.truststore.jks ]; then
    echo "Certificates already exist, skipping generation"
    exit 0
fi

# Generate private key
openssl genrsa -out /certs/zookeeper.key 2048

# Generate certificate signing request
openssl req -new -key /certs/zookeeper.key -out /certs/zookeeper.csr \
    -subj "/C=US/ST=CA/L=SF/O=Integr8sCode/CN=zookeeper"

# Generate self-signed certificate
openssl x509 -req -days 365 -in /certs/zookeeper.csr \
    -signkey /certs/zookeeper.key -out /certs/zookeeper.crt

# Create PKCS12 keystore
openssl pkcs12 -export -in /certs/zookeeper.crt -inkey /certs/zookeeper.key \
    -out /certs/zookeeper.p12 -name zookeeper \
    -password pass:zookeeper_keystore_password

# Remove existing keystore if it exists
rm -f /certs/zookeeper.keystore.jks

# Convert PKCS12 to JKS
keytool -importkeystore \
    -deststorepass zookeeper_keystore_password \
    -destkeypass zookeeper_keystore_password \
    -destkeystore /certs/zookeeper.keystore.jks \
    -srckeystore /certs/zookeeper.p12 \
    -srcstoretype PKCS12 \
    -srcstorepass zookeeper_keystore_password \
    -alias zookeeper \
    -noprompt

# Remove existing truststore if it exists
rm -f /certs/zookeeper.truststore.jks

# Create truststore
keytool -keystore /certs/zookeeper.truststore.jks -alias zookeeper \
    -import -file /certs/zookeeper.crt \
    -storepass zookeeper_truststore_password -noprompt

# Set permissions
chmod 644 /certs/*

echo "Zookeeper certificates generated successfully"
ls -la /certs/