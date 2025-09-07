#!/bin/sh
set -e

# Define a writable directory for our patched config
WRITABLE_KUBECONFIG_DIR="/tmp/kube"
mkdir -p "$WRITABLE_KUBECONFIG_DIR"

# --- CI-Specific Kubeconfig Patching ---
echo "--- Cert-Generator Debug Info ---"
echo "CI environment variable is: [${CI}]"
echo "Checking for original kubeconfig at /root/.kube/config..."
if [ -f /root/.kube/config ]; then
  ls -l /root/.kube/config
else
  echo "Original kubeconfig not found."
fi
echo "--- End Debug Info ---"

if [ "$CI" = "true" ] && [ -f /root/.kube/config ]; then
  echo "CI environment detected. Creating a patched kubeconfig..."
  # Read from the read-only original and write the patched version to our new file
  sed 's|server: https://127.0.0.1:6443|server: https://host.docker.internal:6443|g' /root/.kube/config > "${WRITABLE_KUBECONFIG_DIR}/config"

  # Point the KUBECONFIG variable to our new, writable, and patched file
  export KUBECONFIG="${WRITABLE_KUBECONFIG_DIR}/config"

  echo "Kubeconfig patched and new config is at ${KUBECONFIG}."
  echo "--- Patched Kubeconfig Contents ---"
  cat "${KUBECONFIG}"
  echo "--- End Patched Kubeconfig ---"
else
  echo "Not a CI environment or required conditions not met, proceeding with default setup."
  # If not in CI, we still want kubectl to work if a default config is mounted
  if [ -f /root/.kube/config ]; then
    export KUBECONFIG=/root/.kube/config
  fi
fi
# --- End of CI Patching ---

# From this point on, all `kubectl` commands will automatically use the correct config
# because the KUBECONFIG environment variable is set.

# --- Configuration ---
BACKEND_CERT_DIR=${BACKEND_CERT_DIR:-/backend-certs}
FRONTEND_CERT_DIR=${FRONTEND_CERT_DIR:-/frontend-certs}

mkdir -p "$BACKEND_CERT_DIR" "$FRONTEND_CERT_DIR"

# --- Generate ONE Self-Signed Certificate for the Backend ---
echo "Generating self-signed certificate for backend..."
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$BACKEND_CERT_DIR/server.key" \
  -out "$BACKEND_CERT_DIR/server.crt" \
  -subj "/CN=backend" \
  -addext "subjectAltName = DNS:backend,DNS:localhost,IP:127.0.0.1,IP:::1" \
  -days 365

# Copy the same certificate for the frontend to use.
# The frontend server will use this for its own HTTPS, and the proxy will trust this exact file.
cp "$BACKEND_CERT_DIR/server.crt" "$FRONTEND_CERT_DIR/server.crt"
cp "$BACKEND_CERT_DIR/server.key" "$FRONTEND_CERT_DIR/server.key"

# Copy the certificate to shared CA directory so frontend proxy can trust it
if [ -n "$SHARED_CA_DIR" ]; then
    cp "$BACKEND_CERT_DIR/server.crt" "$SHARED_CA_DIR/mkcert-ca.pem"
    echo "Certificate copied to shared CA directory"
fi

echo "Self-signed certificate created and copied."


# --- Generate Kubeconfig ---
if [ -d /backend ]; then
    echo "Checking if Kubernetes is available..."
    echo "Using KUBECONFIG: ${KUBECONFIG}"
    
    # Try to connect to Kubernetes, but don't fail if it's not available
    if kubectl version --request-timeout=5s >/dev/null 2>&1; then
        echo "Kubernetes cluster detected. Setting up kubeconfig..."
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
    # Create namespace if it doesn't exist
    kubectl create namespace integr8scode --dry-run=client -o yaml | kubectl apply -f -
    
    # Create ClusterRole for namespace listing
    kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: integr8scode-namespace-reader
rules:
- apiGroups: [""]
  resources: ["namespaces"]
  verbs: ["get", "list"]
EOF
    # Create ClusterRoleBinding
    kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: integr8scode-namespace-reader-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: integr8scode-namespace-reader
subjects:
- kind: ServiceAccount
  name: integr8scode-sa
  namespace: default
EOF
    # Create Role for namespace-specific permissions
    kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: integr8scode-role
  namespace: integr8scode
rules:
- apiGroups: ["", "metrics.k8s.io"]
  resources: ["configmaps", "pods", "pods/log", "pods/exec", "nodes", "services"]
  verbs: ["create", "get", "list", "watch", "delete", "patch", "update"]
- apiGroups: ["apps"]
  resources: ["daemonsets"]
  verbs: ["get", "list", "watch", "create", "delete", "replace", "update"]
- apiGroups: ["networking.k8s.io"]
  resources: ["networkpolicies"]
  verbs: ["get", "list", "watch", "create", "delete"]
EOF
    kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: integr8scode-rolebinding
  namespace: integr8scode
subjects:
- kind: ServiceAccount
  name: integr8scode-sa
  namespace: default
roleRef:
  kind: Role
  name: integr8scode-role
  apiGroup: rbac.authorization.k8s.io
EOF
    TOKEN=$(kubectl create token integr8scode-sa -n default --duration=24h)
    K8S_SERVER=$(kubectl config view --raw -o jsonpath='{.clusters[0].cluster.server}')
    
    # In CI, ensure the generated kubeconfig also uses host.docker.internal
    if [ "$CI" = "true" ]; then
        K8S_SERVER=$(echo "$K8S_SERVER" | sed 's|https://127.0.0.1:|https://host.docker.internal:|')
        echo "CI: Patched K8S_SERVER to ${K8S_SERVER}"
    fi
    
    if [ "$USE_DOCKER_HOST" = "true" ]; then
        # Containers in app-network need host.docker.internal to reach the host
        K8S_SERVER="https://host.docker.internal:6443"
        echo "Docker: Set K8S_SERVER to ${K8S_SERVER} (for container access)"
    fi
    
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
    
    # --- Setup NetworkPolicy for Security ---
    echo "Setting up NetworkPolicy for integr8scode namespace..."
    
    # Apply NetworkPolicy to deny all traffic for executor pods
    # This uses standard Kubernetes NetworkPolicy that works with k3s/flannel
    kubectl apply -f - <<'EOF'
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: executor-deny-all
  namespace: integr8scode
spec:
  podSelector:
    matchLabels:
      app: integr8s
      component: executor
  policyTypes:
  - Ingress
  - Egress
  # Empty rules = deny all traffic (no ingress, no egress)
EOF
    
    # Verify the policy was created
    if kubectl get networkpolicy executor-deny-all -n integr8scode >/dev/null 2>&1; then
        echo "✓ NetworkPolicy created successfully in integr8scode namespace"
        
        # Check if NetworkPolicy controller is enabled
        # Note: k3s may have --disable-network-policy flag set
        echo ""
        echo "⚠️  IMPORTANT: NetworkPolicy requires k3s to have network policy enabled."
        echo "   If executor pods still have network access, enable it with:"
        echo "   sudo sed -i \"/'--disable-network-policy'/d\" /etc/systemd/system/k3s.service"
        echo "   sudo systemctl daemon-reload && sudo systemctl restart k3s"
    else
        echo "⚠️  WARNING: Failed to create NetworkPolicy"
    fi
    
    fi
fi

echo "Setup completed successfully."
