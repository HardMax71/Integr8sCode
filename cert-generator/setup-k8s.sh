#!/bin/sh
set -e

export CAROOT=${SHARED_CA_DIR:-/shared_ca}
BACKEND_CERT_DIR=${BACKEND_CERT_DIR:-/backend-certs}
FRONTEND_CERT_DIR=${FRONTEND_CERT_DIR:-/frontend-certs}

mkdir -p "$BACKEND_CERT_DIR" "$FRONTEND_CERT_DIR" "$CAROOT"

if [ -f "$CAROOT/rootCA.pem" ] && [ -f "$CAROOT/rootCA-key.pem" ]; then
    echo "Using existing shared root CA from $CAROOT"
else
    echo "Creating new root CA in shared location $CAROOT"
    mkcert -install
    chmod 644 "$CAROOT/rootCA.pem" "$CAROOT/rootCA-key.pem"
    echo "Root CA created in $CAROOT"
fi

if [ ! -f "$BACKEND_CERT_DIR/server.crt" ]; then
    echo "Generating backend certificates using shared root CA into $BACKEND_CERT_DIR"
    mkcert -cert-file "$BACKEND_CERT_DIR/server.crt" -key-file "$BACKEND_CERT_DIR/server.key" localhost kubernetes.docker.internal backend 127.0.0.1 ::1
    cp "$CAROOT/rootCA.pem" "$BACKEND_CERT_DIR/rootCA.pem"
    chmod 644 "$BACKEND_CERT_DIR/server.crt" "$BACKEND_CERT_DIR/server.key" "$BACKEND_CERT_DIR/rootCA.pem"
    echo "Backend certificates generated using shared root CA"
else
    echo "Backend certificates already exist in $BACKEND_CERT_DIR"
fi

if [ ! -f "$FRONTEND_CERT_DIR/server.crt" ]; then
    echo "Generating frontend certificates using shared root CA into $FRONTEND_CERT_DIR"
    mkcert -cert-file "$FRONTEND_CERT_DIR/server.crt" -key-file "$FRONTEND_CERT_DIR/server.key" localhost kubernetes.docker.internal frontend 127.0.0.1 ::1
    cp "$CAROOT/rootCA.pem" "$FRONTEND_CERT_DIR/rootCA.pem"
    chmod 644 "$FRONTEND_CERT_DIR/server.crt" "$FRONTEND_CERT_DIR/server.key" "$FRONTEND_CERT_DIR/rootCA.pem"
    echo "Frontend certificates generated using shared root CA"
else
    echo "Frontend certificates already exist in $FRONTEND_CERT_DIR"
fi

if [ "$CI" = "true" ] || [ -f /backend/kubeconfig.yaml ]; then
    echo "CI environment detected or kubeconfig already exists. Skipping Kubernetes setup."
else
    if [ -d /backend ]; then
        echo "Generating kubeconfig for backend"
        if ! kubectl config view > /dev/null 2>&1; then
            echo "ERROR: kubectl is not configured properly. Exiting."
            exit 1
        fi
        K8S_CA_CERT=$(kubectl config view --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')
        if [ -z "$K8S_CA_CERT" ]; then
            echo "ERROR: Failed to get Kubernetes CA certificate. Exiting."
            exit 1
        fi
        kubectl create serviceaccount integr8scode-sa -n default --dry-run=client -o yaml | kubectl apply -f -
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
        TOKEN=$(kubectl create token integr8scode-sa -n default --duration=24h)
        if [ -z "$TOKEN" ]; then
            echo "ERROR: Failed to generate token. Exiting."
            exit 1
        fi
        if [ -n "$KUBERNETES_SERVICE_HOST" ]; then
            K8S_SERVER="https://${KUBERNETES_SERVICE_HOST}:${KUBERNETES_SERVICE_PORT}"
        else
            K8S_SERVER="https://kubernetes.docker.internal:6443"
        fi
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

echo "$(date)" > "$BACKEND_CERT_DIR/setup-complete"
echo "$(date)" > "$FRONTEND_CERT_DIR/setup-complete"

echo "Setup completed successfully. Exiting."