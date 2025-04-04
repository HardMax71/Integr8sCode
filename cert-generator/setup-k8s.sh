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

# Skip Kubernetes setup if CI environment is detected or if kubeconfig already exists
if [ "$CI" = "true" ] || [ -f /backend/kubeconfig.yaml ]; then
    echo "CI environment detected or kubeconfig already exists. Skipping Kubernetes setup."
else
    # Generate kubeconfig dynamically for backend container
    if [ -d /backend ]; then
        echo "Generating kubeconfig for backend"

        # Check if kubectl is properly configured
        if ! kubectl config view > /dev/null 2>&1; then
            echo "ERROR: kubectl is not configured properly. Exiting."
            exit 1
        fi

        # Fetch Kubernetes CA Certificate dynamically
        K8S_CA_CERT=$(kubectl config view --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')
        if [ -z "$K8S_CA_CERT" ]; then
            echo "ERROR: Failed to get Kubernetes CA certificate. Exiting."
            exit 1
        fi

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
        if [ -z "$TOKEN" ]; then
            echo "ERROR: Failed to generate token. Exiting."
            exit 1
        fi

        # Determine appropriate Kubernetes server URL
        if [ -n "$KUBERNETES_SERVICE_HOST" ]; then
            # Inside Kubernetes cluster
            K8S_SERVER="https://${KUBERNETES_SERVICE_HOST}:${KUBERNETES_SERVICE_PORT}"
        else
            # Local development
            K8S_SERVER="https://kubernetes.docker.internal:6443"
        fi

        # Create kubeconfig
        cat > /backend/kubeconfig.yaml <<EOF
apiVersion: v1
kind: Config
clusters:
- name: docker-desktop
  cluster:
    server: ${K8S_SERVER}
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
fi

# Marker file to indicate setup completion
echo "$(date)" > /certs/setup-complete

# Final log
echo "Setup completed successfully. Exiting."