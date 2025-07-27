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

# Function to detect the correct host IP for k3s access from Docker
detect_docker_host_ip() {
  # First check if K3S_HOST_IP environment variable is explicitly set
  if [ -n "$K3S_HOST_IP" ]; then
    echo "$K3S_HOST_IP"
    return
  fi
  
  # Try host.docker.internal first (works on Docker Desktop for Mac/Windows)
  if getent hosts host.docker.internal > /dev/null 2>&1; then
    echo "host.docker.internal"
    return
  fi
  
  # If host.docker.internal doesn't work, try to ping it to see if it resolves
  if ping -c 1 host.docker.internal > /dev/null 2>&1; then
    echo "host.docker.internal"
    return
  fi
  
  # Check if we're using host networking (no .dockerenv means host network)
  if [ ! -f /.dockerenv ]; then
    echo "127.0.0.1"
    return
  fi
  
  # Fall back to Docker bridge gateway (typically Linux)
  echo "172.17.0.1"
}

if [ "$CI" = "true" ] && [ -f /root/.kube/config ]; then
  echo "CI environment detected. Creating a patched kubeconfig..."
  # Read from the read-only original and write the patched version to our new file
  sed 's|server: https://127.0.0.1:6443|server: https://host.docker.internal:6443|g' /root/.kube/config > "${WRITABLE_KUBECONFIG_DIR}/config"
elif [ -f /root/.kube/config ] && grep -q "server:" /root/.kube/config; then
  echo "Detected kubeconfig with k3s/k8s. Patching for Docker access..."
  # For non-CI environments, we need to ensure k3s is accessible from within Docker
  # Try to detect if we're in Docker and k3s is on the host
  if [ -f /.dockerenv ]; then
    # We're in a Docker container - need to patch the config
    DOCKER_HOST_IP=$(detect_docker_host_ip)
    echo "Detected Docker host IP: ${DOCKER_HOST_IP}"
    
    sed "s|server: https://[^:]*:6443|server: https://${DOCKER_HOST_IP}:6443|g" /root/.kube/config > "${WRITABLE_KUBECONFIG_DIR}/config"
    echo "Patched kubeconfig to use ${DOCKER_HOST_IP} for k3s access from Docker"
    export KUBECONFIG="${WRITABLE_KUBECONFIG_DIR}/config"
  fi

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
  -addext "subjectAltName = DNS:backend,DNS:localhost" \
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
    echo "Ensuring kubeconfig is up to date"
    
    # In CI without a real K8s cluster, create a dummy kubeconfig
    if [ "$CI" = "true" ] && ! kubectl cluster-info > /dev/null 2>&1; then
        echo "CI detected without K8s cluster - creating dummy kubeconfig for testing"
        cat > /backend/kubeconfig.yaml <<EOF
apiVersion: v1
kind: Config
clusters:
- name: docker-desktop
  cluster:
    server: https://127.0.0.1:6443
    certificate-authority-data: LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSUJkekNDQVIyZ0F3SUJBZ0lCQURBS0JnZ3Foa2pPUFFRREFqQWpNU0V3SHdZRFZRUUREQmhyTTNNdGMyVnkKZG1WeUxXTmhRREUyTnpjeU5UazVPVGN3SGhjTk1qSXhNakU1TVRVMU9UTTNXaGNOTXpJeE1qRTJNVFUxT1RNMwpXakFqTVNFd0h3WURWUVFEREJock0zTXRjMlZ5ZG1WeUxXTmhRREUyTnpjeU5UazVPVGN3V1RBVEJnY3Foa2pPClBRSUJCZ2dxaGtqT1BRTUJCd05DQUFSVnNKeWlqc3hJOGl6cGFQRVlIcEo0WGdFTG9xbVlLMXkwSytNMWlTMUwKa1d2d2JkcGZ0MXAwUFRLMTU0K2xia0JnbHVBdG9vSFJJUTg4MjZpcENLMDhvMEl3UURBT0JnTlZIUThCQWY4RQpCQU1DQXFRd0R3WURWUjBUQVFIL0JBVXdBd0VCL3pBZEJnTlZIUTRFRmdRVTlXRUpWNGcvWGh5YkpBWUhIQXVOCldJNnYvNll3Q2dZSUtvWkl6ajBFQXdJRFNBQXdSUUloQU1wNFRtakg5NWRYQnBGNmtCcFdKaWsxT3BYV0tMNzYKaHJKdVFYRXJJOGZlQWlBWk8rL2NsVklrd0Yvb0VuSEhZeHJCRGxHQzR2ekxIa2k2SFMvMUFCWkV3Zz09Ci0tLS0tRU5EIENFUlRJRklDQVRFLS0tLS0K
users:
- name: integr8scode-sa
  user:
    token: "dummy-token-for-ci-testing"
contexts:
- name: integr8scode
  context:
    cluster: docker-desktop
    user: integr8scode-sa
current-context: integr8scode
EOF
        chmod 644 /backend/kubeconfig.yaml
        echo "Dummy kubeconfig.yaml created for CI testing."
        echo "Setup completed successfully."

# Create a setup-complete file to indicate success
touch /backend/setup-complete || true
        exit 0
    fi
    
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
  resources: ["configmaps", "pods", "pods/log", "pods/exec", "nodes", "services"]
  verbs: ["create", "get", "list", "watch", "delete"]
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
    # When running in Docker, need to use appropriate host IP
    if [ -f /.dockerenv ]; then
        DOCKER_HOST_IP=$(detect_docker_host_ip)
        K8S_SERVER=$(echo "$K8S_SERVER" | sed "s|https://[^:]*:|https://${DOCKER_HOST_IP}:|")
        echo "Running in Docker, using ${DOCKER_HOST_IP} for k3s server"
    else
        # Otherwise use localhost
        K8S_SERVER=$(echo "$K8S_SERVER" | sed 's|https://[^:]*:|https://127.0.0.1:|')
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
fi

echo "Setup completed successfully."

# Create a setup-complete file to indicate success
touch /backend/setup-complete || true