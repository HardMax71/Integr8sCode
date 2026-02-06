# Network Isolation

Executor pods run user code in a hardened environment with strict security controls. The pod builder in `backend/app/services/k8s_worker/pod_builder.py` enforces these at pod creation time.

## Container Security Context

Each executor container runs with:

- Non-root user (UID/GID 1000)
- Read-only root filesystem
- No privilege escalation allowed
- All Linux capabilities dropped
- RuntimeDefault seccomp profile

The pod spec also sets `automount_service_account_token: false`, preventing containers from accessing the Kubernetes API.

## Network Policy

Network isolation uses a standard Kubernetes NetworkPolicy that denies all ingress and egress traffic from executor pods. The policy is applied during cluster setup.

```yaml
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
```

This policy matches pods with labels `app=integr8s` and `component=executor`, which the pod builder applies to all executor pods.

## Setup

The network policy and RBAC resources are created by the setup script during initial deployment:

```bash
./cert-generator/setup-k8s.sh
```

This script creates the `integr8scode` namespace, a ServiceAccount with appropriate permissions, and the deny-all NetworkPolicy.

## Notes

The NetworkPolicy requires a CNI plugin that supports network policies (Calico, Cilium, Weave Net, etc). K3s includes Flannel by default, which does not enforce policies. For production, install a policy-capable CNI or use K3s with the `--flannel-backend=none` flag and a separate CNI.

To allow specific egress traffic (for example, to internal services), create an additional NetworkPolicy with explicit egress rules rather than modifying the deny-all policy.
