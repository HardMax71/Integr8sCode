#!/bin/sh
set -e

# Set CAROOT to use the shared directory for root CA
export CAROOT=/shared_ca

# Check if a shared root CA already exists
if [ -f "$CAROOT/rootCA.pem" ] && [ -f "$CAROOT/rootCA-key.pem" ]; then
    echo "Using existing shared root CA from $CAROOT"
else
    echo "Creating new root CA in shared location $CAROOT"
    # Generate a new root CA
    mkcert -install
    chmod 644 "$CAROOT/rootCA.pem" "$CAROOT/rootCA-key.pem"
    echo "Root CA created in $CAROOT"
fi

# Generate certificates if they don't exist
if [ ! -f /certs/server.crt ]; then
    echo "Generating certificates using shared root CA"
    mkcert -cert-file /certs/server.crt -key-file /certs/server.key localhost kubernetes.docker.internal 127.0.0.1 ::1
    cp "$CAROOT/rootCA.pem" /certs/rootCA.pem
    chmod 644 /certs/server.crt /certs/server.key /certs/rootCA.pem
    echo "Certificates generated using shared root CA"
else
    echo "Certificates already exist"
fi

# Only generate kubeconfig for backend container
if [ -d /backend ]; then
    # Get the actual k8s API server CA cert
    K8S_CA_CERT=$(kubectl config view --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')

    # Create the service account and extract its token
    kubectl create serviceaccount integr8scode-sa -n default --dry-run=client -o yaml | kubectl apply -f -

    # Create the role with necessary permissions
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

    # Bind the role to your service account
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

    # Write k8s CA cert separately
    echo "$K8S_CA_CERT" | base64 -d > /certs/k8s-ca.pem
    chmod 644 /certs/k8s-ca.pem

    # Generate kubeconfig using the k8s CA cert
    cat > /backend/kubeconfig.yaml << EOF
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

    echo "Generated kubeconfig with k8s CA cert and token"
fi

# Create a marker file to indicate completion
echo "$(date)" > /certs/setup-complete

echo "Setup completed successfully. Exiting."