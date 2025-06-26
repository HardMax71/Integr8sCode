#!/bin/sh
set -e

# --- Configuration ---
BACKEND_CERT_DIR=${BACKEND_CERT_DIR:-/backend-certs}
FRONTEND_CERT_DIR=${FRONTEND_CERT_DIR:-/frontend-certs} # We still need this directory

mkdir -p "$BACKEND_CERT_DIR" "$FRONTEND_CERT_DIR"

# --- Generate ONE Self-Signed Certificate for the Backend ---
echo "Generating self-signed certificate for backend..."
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$BACKEND_CERT_DIR/server.key" \
  -out "$BACKEND_CERT_DIR/server.crt" \
  -subj "/CN=backend" \
  -addext "subjectAltName = DNS:backend,DNS:localhost" \
  -days 365

# Copy the same certificate for the frontend to use.
# The frontend server will use this for its own HTTPS, and the proxy will trust this exact file.
cp "$BACKEND_CERT_DIR/server.crt" "$FRONTEND_CERT_DIR/server.crt"
cp "$BACKEND_CERT_DIR/server.key" "$FRONTEND_CERT_DIR/server.key"

echo "Self-signed certificate created and copied."


# --- Generate Kubeconfig ---
if [ -d /backend ]; then
    echo "Ensuring kubeconfig is up to date"
    if ! kubectl config view --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' > /dev/null 2>&1; then
        echo "ERROR: kubectl is not configured to connect to a cluster."
        exit 1
    fi
    K8S_CA_CERT_B64=$(kubectl config view --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')
    kubectl apply -f - <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: integr8scode-sa
  namespace: default
EOF
    kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: integr8scode-role
rules:
- apiGroups: ["", "metrics.k8s.io"]
  resources: ["configmaps", "pods", "pods/log", "nodes", "services"]
  verbs: ["create", "get", "list", "watch", "delete"]
EOF
    kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: integr8scode-rolebinding
subjects:
- kind: ServiceAccount
  name: integr8scode-sa
roleRef:
  kind: Role
  name: integr8scode-role
  apiGroup: rbac.authorization.k8s.io
EOF
    TOKEN=$(kubectl create token integr8scode-sa -n default --duration=24h)
    K8S_SERVER=$(kubectl config view --raw -o jsonpath='{.clusters[0].cluster.server}')
    cat > /backend/kubeconfig.yaml <<EOF
apiVersion: v1
kind: Config
clusters:
- name: docker-desktop
  cluster:
    server: ${K8S_SERVER}
    certificate-authority-data: ${K8S_CA_CERT_B64}
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
    echo "kubeconfig.yaml successfully generated."
fi

echo "Setup completed successfully."