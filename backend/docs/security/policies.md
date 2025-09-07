Executor Pod Network Isolation (Cilium)

Overview
- Executor pods are hardened (non-root, no caps, read-only root FS, no service account, DNS disabled).
- Network isolation is enforced exclusively via a static CiliumNetworkPolicy.
- Per-execution NetworkPolicy creation has been removed from the worker.
- Using the 'default' namespace is forbidden; apply policies and run pods in a dedicated namespace.

Apply deny-all Cilium policy
- File: backend/k8s/policies/executor-deny-all-cnp.yaml
- Use the setup script (namespace required):
  - ./backend/scripts/setup_k8s.sh <namespace>
  - This creates the namespace if needed and applies the CNP there.

Labels matched
- app=integr8s
- component=executor

Notes
- Ensure Cilium is installed and policy enforcement is active.
- To allow in-cluster traffic later, modify egress rules (e.g., toEntities: ["cluster"]).
