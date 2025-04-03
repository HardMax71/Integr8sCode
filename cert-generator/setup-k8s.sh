#!/bin/sh
set -e

# Set CAROOT to use the shared directory for root CA
export CAROOT=/shared_ca

# Check if a shared root CA already exists
if [ -f "$CAROOT/rootCA.pem" ] && [ -f "$CAROOT/rootCA-key.pem" ]; then
    echo "Using existing shared root CA from $CAROOT"
else
    echo "Creating new root CA in shared location $CAROOT"
    mkcert -install
    chmod 644 "$CAROOT/rootCA.pem" "$CAROOT/rootCA-key.pem"
    echo "Root CA created in $CAROOT"
fi

# Generate certificates if they don't exist
if [ ! -f /certs/server.crt ]; then
    echo "Generating certificates using shared root CA"
    mkcert -cert-file /certs/server.crt -key-file /certs/server.key localhost kubernetes.docker.internal backend 127.0.0.1 ::1
    cp "$CAROOT/rootCA.pem" /certs/rootCA.pem
    chmod 644 /certs/server.crt /certs/server.key /certs/rootCA.pem
    echo "Certificates generated using shared root CA"
else
    echo "Certificates already exist"
fi

# Generate kubeconfig dynamically for backend container
if [ -d /backend ]; then
    echo "Generating kubeconfig for backend"

    # Fetch Kubernetes CA Certificate dynamically
    K8S_CA_CERT=$(kubectl config view --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')

    # Create service account for backend access
    kubectl create serviceaccount integr8scode-sa -n default --dry-run=client -o yaml | kubectl apply -f -

    # Apply RBAC role for service account
    kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: integr8scode-role
  namespace: default
rules:
- apiGroups: [""]
  resources: ["configmaps", "pods", "pods/log"]
  verbs: ["create", "get", "list", "watch", "delete"]
EOF

    # Bind the role to service account
    kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: integr8scode-rolebinding
  namespace: default
subjects:
- kind: ServiceAccount
  name: integr8scode-sa
  namespace: default
roleRef:
  kind: Role
  name: integr8scode-role
  apiGroup: rbac.authorization.k8s.io
EOF

    # Generate short-lived token for the service account
    TOKEN=$(kubectl create token integr8scode-sa -n default --duration=24h)

    # Write Kubernetes CA cert to file
    echo "$K8S_CA_CERT" | base64 -d > /certs/k8s-ca.pem
    chmod 644 /certs/k8s-ca.pem

    # Create kubeconfig
    cat > /backend/kubeconfig.yaml <<EOF
apiVersion: v1
kind: Config
clusters:
- name: docker-desktop
  cluster:
    server: https://kubernetes.docker.internal:6443
    certificate-authority-data: ${K8S_CA_CERT}
users:
- name: integr8scode-sa
  user:
    token: "${TOKEN}"
contexts:
- name: integr8scode
  context:
    cluster: docker-desktop
    user: integr8scode-sa
current-context: integr8scode
EOF

    chmod 644 /backend/kubeconfig.yaml

    echo "kubeconfig.yaml successfully generated at /backend/kubeconfig.yaml"
fi

# Marker file to indicate setup completion
echo "$(date)" > /certs/setup-complete

# Final log
echo "Setup completed successfully. Exiting."
