#!/bin/sh
set -e

# Define a writable directory for our patched config
WRITABLE_KUBECONFIG_DIR="/tmp/kube"
mkdir -p "$WRITABLE_KUBECONFIG_DIR"

# --- Docker Kubeconfig Patching ---
echo "--- Cert-Generator Debug Info ---"
echo "Checking for original kubeconfig at /root/.kube/config..."
if [ -f /root/.kube/config ]; then
  ls -l /root/.kube/config
else
  echo "Original kubeconfig not found."
  echo "ERROR: No kubeconfig found. Cannot proceed."
  exit 1
fi
echo "--- End Debug Info ---"

# Always patch kubeconfig when running in Docker container
if [ -f /root/.kube/config ]; then
  echo "Patching kubeconfig for Docker container access..."

  # Test which IP can reach k3s from container
  K8S_PORT=6443
  WORKING_IP=""

  # List of potential IPs to test - include loopback and gateway for host networking
  GATEWAY_IP=$(ip route | awk '/default/ {print $3; exit}')
  # Try common patterns for host IPs, plus loopback and detected gateway
  for TEST_IP in 127.0.0.1 ${GATEWAY_IP} 192.168.0.16 192.168.1.1 10.0.0.1 172.17.0.1 172.18.0.1 host.docker.internal; do
    echo -n "Testing ${TEST_IP}:${K8S_PORT}... "
    if nc -zv -w2 ${TEST_IP} ${K8S_PORT} 2>/dev/null; then
      WORKING_IP=${TEST_IP}
      echo "✓ SUCCESS"
      break
    fi
    echo "✗ failed"
  done

  if [ -z "$WORKING_IP" ]; then
    echo "ERROR: Cannot find working IP to reach k3s from container"
    echo "Tested IPs: 127.0.0.1, ${GATEWAY_IP}, 192.168.0.16, 192.168.1.1, 10.0.0.1, 172.17.0.1, 172.18.0.1, host.docker.internal"
    exit 1
  fi

  # Read original and patch the server URL to use working IP
  sed "s|server: https://[^:]*:6443|server: https://${WORKING_IP}:6443|g" /root/.kube/config > "${WRITABLE_KUBECONFIG_DIR}/config"

  # Point the KUBECONFIG variable to our new, writable, and patched file
  export KUBECONFIG="${WRITABLE_KUBECONFIG_DIR}/config"

  echo "Kubeconfig patched to use ${WORKING_IP}:6443"
else
  echo "ERROR: kubeconfig not found at /root/.kube/config"
  exit 1
fi
# --- End of Docker Patching ---

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
    
    # Try to connect to Kubernetes - MUST succeed
    if ! kubectl version --request-timeout=5s >/dev/null 2>&1; then
        echo "ERROR: Cannot connect to Kubernetes cluster!"
        echo "  Ensure k3s/k8s is running and accessible"
        exit 1
    fi

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
    
    # Get the original server URL from kubectl
    echo "Original K8S_SERVER from kubectl: ${K8S_SERVER}"

    # Extract just the port from the original URL
    K8S_PORT=$(echo "$K8S_SERVER" | grep -oE ':[0-9]+' | tr -d ':')
    K8S_PORT=${K8S_PORT:-6443}

    # Prefer loopback and gateway IPs first when running with host networking
    GATEWAY_IP=$(ip route | grep default | awk '{print $3}')
    POTENTIAL_IPS="127.0.0.1 ${GATEWAY_IP} 172.18.0.1 172.17.0.1 host.docker.internal"

    echo "Environment info:"
    echo "  K8S_PORT: ${K8S_PORT}"
    echo "  Gateway IP: ${GATEWAY_IP:-none}"
    echo "  Testing endpoints: ${POTENTIAL_IPS}"

    CHOSEN_URL=""
    for IP in $POTENTIAL_IPS; do
        TEST_URL="https://${IP}:${K8S_PORT}"
        echo -n "  Trying ${TEST_URL}... "
        if nc -z -w2 ${IP} ${K8S_PORT} 2>/dev/null; then
            CHOSEN_URL="${TEST_URL}"
            echo "✓ SUCCESS"
            break
        fi
        echo "✗ failed"
    done

    # If none of the alternative endpoints worked, keep the original server URL
    if [ -z "$CHOSEN_URL" ]; then
        echo "No alternative endpoint worked; keeping original K8S_SERVER: ${K8S_SERVER}"
    else
        K8S_SERVER="$CHOSEN_URL"
    fi

    echo "Using K8S_SERVER: ${K8S_SERVER}"
    
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

echo "Setup completed successfully."
