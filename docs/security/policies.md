# Network isolation

Executor pods run user code in a hardened environment: non-root user, no capabilities, read-only root filesystem, no service account token, and DNS disabled. Network isolation is enforced via a static CiliumNetworkPolicy that denies all egress traffic from executor pods.

## Setup

The deny-all Cilium policy is defined in `backend/k8s/policies/executor-deny-all-cnp.yaml`. Apply it using the setup script:

```bash
./backend/scripts/setup_k8s.sh <namespace>
```

This creates the namespace if needed and applies the CiliumNetworkPolicy there. Using the `default` namespace is forbidden — always run executor pods in a dedicated namespace.

## Pod labels

The policy matches pods with these labels:

- `app=integr8s`
- `component=executor`

## Notes

Cilium must be installed with policy enforcement active. To allow in-cluster traffic later (for example, accessing internal services), modify the egress rules in the CNP to include `toEntities: ["cluster"]`.
