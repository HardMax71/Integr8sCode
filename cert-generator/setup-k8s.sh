#!/bin/sh
set -e

echo "Setting up Kubernetes resources..."

# Auto-configure kubectl for k3s if needed
# k3s stores its kubeconfig at /etc/rancher/k3s/k3s.yaml
# When running in bridge network, we need to use the routable host IP instead of 127.0.0.1
configure_kubectl() {
    # If kubectl already works, nothing to do
    if kubectl version --request-timeout=2s >/dev/null 2>&1; then
        return 0
    fi
    # Try k3s kubeconfig with routable IP (for bridge network containers)
    if [ -r /etc/rancher/k3s/k3s.yaml ]; then
        # Get the k3s node-ip from config (routable from containers)
        K3S_HOST_IP=""
        if [ -r /etc/rancher/k3s/config.yaml ]; then
            K3S_HOST_IP=$(grep -E '^node-ip:' /etc/rancher/k3s/config.yaml 2>/dev/null | sed -E 's/^node-ip:[[:space:]]*"?([^"[:space:]]+)"?.*/\1/' | head -1)
        fi
        # If no node-ip found, try to detect host from container (for CI/Docker environments)
        if [ -z "$K3S_HOST_IP" ] || [ "$K3S_HOST_IP" = "127.0.0.1" ]; then
            # Prefer host.docker.internal (works with TLS cert SANs, requires extra_hosts in compose)
            if getent hosts host.docker.internal >/dev/null 2>&1; then
                K3S_HOST_IP="host.docker.internal"
            fi
        fi
        if [ -z "$K3S_HOST_IP" ] || [ "$K3S_HOST_IP" = "127.0.0.1" ]; then
            # Fallback: Docker gateway (may need insecure TLS if IP not in cert SANs)
            K3S_HOST_IP=$(ip route 2>/dev/null | grep default | awk '{print $3}' | head -1)
        fi
        if [ -n "$K3S_HOST_IP" ] && [ "$K3S_HOST_IP" != "127.0.0.1" ]; then
            # Create modified kubeconfig with routable IP/hostname
            # Handle both 127.0.0.1 and 0.0.0.0 (k3s may use either depending on config)
            mkdir -p /tmp/kube
            sed -E "s#https://(127\.0\.0\.1|0\.0\.0\.0):#https://${K3S_HOST_IP}:#g" /etc/rancher/k3s/k3s.yaml > /tmp/kube/config
            export KUBECONFIG=/tmp/kube/config
            echo "Using k3s kubeconfig with routable IP: $K3S_HOST_IP"
        else
            export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
            echo "Using k3s kubeconfig: $KUBECONFIG"
        fi
        return 0
    fi
    return 1
}

configure_kubectl || true

# In CI mode, skip k8s setup if connection fails
if [ -n "$CI" ]; then
    echo "Running in CI mode"
    if ! kubectl version --request-timeout=5s >/dev/null 2>&1; then
        echo "WARNING: Cannot connect to Kubernetes in CI - skipping k8s setup"
        echo "Creating dummy kubeconfig for CI..."
        mkdir -p /backend
        cat > /backend/kubeconfig.yaml <<EOF
apiVersion: v1
kind: Config
clusters:
- name: ci-cluster
  cluster:
    server: https://host.docker.internal:6443
    insecure-skip-tls-verify: true
users:
- name: ci-user
  user:
    token: "ci-token"
contexts:
- name: ci
  context:
    cluster: ci-cluster
    user: ci-user
current-context: ci
EOF
        echo "✅ Dummy kubeconfig created for CI"
        exit 0
    fi
fi

# Check k8s connection (single attempt — k3s should already be running)
echo "Checking Kubernetes connection..."
if ! kubectl version --request-timeout=10s >/dev/null 2>&1; then
    echo "ERROR: Cannot connect to Kubernetes cluster"
    exit 1
fi
echo "Connected to Kubernetes"

# Create namespace
kubectl create namespace integr8scode --dry-run=client -o yaml | kubectl apply -f -

# Create ServiceAccount
kubectl apply -f - <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: integr8scode-sa
  namespace: default
EOF

# Create ClusterRole
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

# Create Role
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

# Create RoleBinding
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

# NetworkPolicy
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
EOF

# Resolve current context/cluster and extract server + CA (no insecure fallback)
CTX=$(kubectl config current-context)
echo "Context: ${CTX}"
CLUSTER_NAME=$(kubectl config view -o jsonpath='{.contexts[?(@.name=="'$CTX'")].context.cluster}')
echo "Resolved cluster: ${CLUSTER_NAME}"
K8S_SERVER=$(kubectl config view --raw -o jsonpath='{.clusters[?(@.name=="'$CLUSTER_NAME'")].cluster.server}')
echo "Server (host kubeconfig): ${K8S_SERVER}"
SERVER_HOST=$(echo "$K8S_SERVER" | sed -E 's#https?://([^/:]+).*#\1#')
K8S_PORT=$(echo "$K8S_SERVER" | sed -nE 's#.*:([0-9]+).*#\1#p')
K8S_PORT=${K8S_PORT:-6443}
echo "Parsed server host: ${SERVER_HOST}"
echo "Parsed API port: ${K8S_PORT}"
CA_CERT=$(kubectl config view --raw -o jsonpath='{.clusters[?(@.name=="'$CLUSTER_NAME'")].cluster.certificate-authority-data}')
CA_SOURCE="embedded"
if [ -z "$CA_CERT" ]; then
  CA_FILE=$(kubectl config view --raw -o jsonpath='{.clusters[?(@.name=="'$CLUSTER_NAME'")].cluster.certificate-authority}')
  if [ -n "$CA_FILE" ] && [ -f "$CA_FILE" ]; then
    CA_CERT=$(base64 < "$CA_FILE" | tr -d '\n')
    CA_SOURCE="file: ${CA_FILE}"
  else
    echo "ERROR: Missing certificate-authority-data and certificate-authority file for cluster: $CLUSTER_NAME"
    exit 1
  fi
fi
echo "CA source: ${CA_SOURCE}"

# Generate token
TOKEN=$(kubectl create token integr8scode-sa -n default --duration=24h)
TOKEN_LEN=$(printf %s "$TOKEN" | wc -c | awk '{print $1}')
TOKEN_HEAD=$(printf %s "$TOKEN" | cut -c1-10)
echo "ServiceAccount token acquired (len=${TOKEN_LEN}, head=${TOKEN_HEAD}...)"

# Determine the host IP that containers can reach
# Priority: 1) k3s node-ip config, 2) server URL from kubeconfig, 3) fallback to host.docker.internal
get_container_host_ip() {
    # Try k3s config node-ip (most reliable for k3s setups)
    if [ -f /etc/rancher/k3s/config.yaml ]; then
        K3S_NODE_IP=$(grep -E '^node-ip:' /etc/rancher/k3s/config.yaml 2>/dev/null | sed -E 's/^node-ip:[[:space:]]*"?([^"[:space:]]+)"?.*/\1/' | head -1)
        if [ -n "$K3S_NODE_IP" ] && [ "$K3S_NODE_IP" != "127.0.0.1" ]; then
            echo "$K3S_NODE_IP"
            return
        fi
    fi
    # Try extracting from kubeconfig server URL (if not localhost)
    if [ -n "$SERVER_HOST" ] && [ "$SERVER_HOST" != "127.0.0.1" ] && [ "$SERVER_HOST" != "localhost" ]; then
        echo "$SERVER_HOST"
        return
    fi
    # Fallback to host.docker.internal (works on Docker Desktop, may need extra_hosts on Linux)
    echo "host.docker.internal"
}

CONTAINER_HOST_IP=$(get_container_host_ip)
CONTAINER_SERVER="https://${CONTAINER_HOST_IP}:${K8S_PORT}"
echo "Detected container-accessible host IP: ${CONTAINER_HOST_IP}"

echo "Writing kubeconfig for containers:"
echo "  cluster: ${CLUSTER_NAME}"
echo "  server (container view): ${CONTAINER_SERVER}"
echo "  tls-server-name (cert host): ${SERVER_HOST}"

cat > /backend/kubeconfig.yaml <<EOF
apiVersion: v1
kind: Config
clusters:
- name: ${CLUSTER_NAME}
  cluster:
    server: ${CONTAINER_SERVER}
    certificate-authority-data: ${CA_CERT}
    tls-server-name: ${SERVER_HOST}
users:
- name: integr8scode-sa
  user:
    token: "${TOKEN}"
contexts:
- name: integr8scode
  context:
    cluster: ${CLUSTER_NAME}
    user: integr8scode-sa
current-context: integr8scode
EOF

chmod 644 /backend/kubeconfig.yaml
echo "✅ K8s setup complete! Kubeconfig written to /backend/kubeconfig.yaml"
echo "   Kubeconfig server: ${CONTAINER_SERVER}"
echo "   Kubeconfig cluster: ${CLUSTER_NAME}"
