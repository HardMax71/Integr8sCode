#!/bin/sh
set -e

echo "Setting up Kubernetes resources..."

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

# Check k8s connection
if ! kubectl version --request-timeout=5s >/dev/null 2>&1; then
    echo "ERROR: Cannot connect to Kubernetes cluster!"
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

# For containers: use host.docker.internal (mapped to host-gateway) but keep TLS host verification via tls-server-name
CONTAINER_SERVER="https://host.docker.internal:${K8S_PORT}"

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
