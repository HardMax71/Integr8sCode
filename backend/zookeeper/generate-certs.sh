#!/bin/sh
set -e

# Check if certificates already exist
if [ -f /certs/zookeeper.keystore.jks ] && [ -f /certs/kafka-client.keystore.jks ]; then
    echo "Certificates already exist, skipping generation"
    exit 0
fi

# 1. Generate CA key and self-signed CA certificate
openssl genrsa -out /certs/ca.key 2048
openssl req -new -x509 -days 365 -key /certs/ca.key -out /certs/ca.crt \
    -subj "/C=US/ST=CA/L=SF/O=Integr8sCode/CN=Integr8sCode-CA"

# 2. Generate Zookeeper server key and CA-signed certificate
openssl genrsa -out /certs/zookeeper.key 2048
openssl req -new -key /certs/zookeeper.key -out /certs/zookeeper.csr \
    -subj "/C=US/ST=CA/L=SF/O=Integr8sCode/CN=zookeeper"
openssl x509 -req -days 365 -in /certs/zookeeper.csr \
    -CA /certs/ca.crt -CAkey /certs/ca.key -CAcreateserial \
    -out /certs/zookeeper.crt

# 3. Generate Kafka client key and CA-signed certificate
openssl genrsa -out /certs/kafka-client.key 2048
openssl req -new -key /certs/kafka-client.key -out /certs/kafka-client.csr \
    -subj "/C=US/ST=CA/L=SF/O=Integr8sCode/CN=kafka"
openssl x509 -req -days 365 -in /certs/kafka-client.csr \
    -CA /certs/ca.crt -CAkey /certs/ca.key -CAcreateserial \
    -out /certs/kafka-client.crt

# 4. Build Zookeeper server keystore (JKS)
rm -f /certs/zookeeper.keystore.jks
openssl pkcs12 -export -in /certs/zookeeper.crt -inkey /certs/zookeeper.key \
    -out /certs/zookeeper.p12 -name zookeeper \
    -password pass:zookeeper_keystore_password
keytool -importkeystore \
    -deststorepass zookeeper_keystore_password \
    -destkeypass zookeeper_keystore_password \
    -destkeystore /certs/zookeeper.keystore.jks \
    -srckeystore /certs/zookeeper.p12 \
    -srcstoretype PKCS12 \
    -srcstorepass zookeeper_keystore_password \
    -alias zookeeper \
    -noprompt

# 5. Build Zookeeper truststore (CA cert — trusts any client signed by the CA)
rm -f /certs/zookeeper.truststore.jks
keytool -keystore /certs/zookeeper.truststore.jks -alias ca \
    -import -file /certs/ca.crt \
    -storepass zookeeper_truststore_password -noprompt

# 6. Build Kafka client keystore (JKS)
rm -f /certs/kafka-client.keystore.jks
openssl pkcs12 -export -in /certs/kafka-client.crt -inkey /certs/kafka-client.key \
    -out /certs/kafka-client.p12 -name kafka \
    -password pass:kafka_keystore_password
keytool -importkeystore \
    -deststorepass kafka_keystore_password \
    -destkeypass kafka_keystore_password \
    -destkeystore /certs/kafka-client.keystore.jks \
    -srckeystore /certs/kafka-client.p12 \
    -srcstoretype PKCS12 \
    -srcstorepass kafka_keystore_password \
    -alias kafka \
    -noprompt

# 7. Build Kafka client truststore (CA cert — trusts Zookeeper's server cert)
rm -f /certs/kafka-client.truststore.jks
keytool -keystore /certs/kafka-client.truststore.jks -alias ca \
    -import -file /certs/ca.crt \
    -storepass kafka_truststore_password -noprompt

# Set permissions
chmod 644 /certs/*

echo "Zookeeper and Kafka certificates generated successfully"
ls -la /certs/
