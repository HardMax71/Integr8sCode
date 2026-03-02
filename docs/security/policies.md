# Pod & Namespace Security

Executor pods run user code in a hardened environment with strict security controls. Defenses are layered across three
levels: container, pod, and namespace.

## Container Security Context

Each executor container runs with:

- Non-root user (UID/GID 1000)
- Read-only root filesystem
- No privilege escalation allowed
- All Linux capabilities dropped
- RuntimeDefault seccomp profile

The pod spec also sets `automount_service_account_token: false`, preventing containers from accessing the Kubernetes
API.

These are enforced by the pod builder in `backend/app/services/k8s_worker/pod_builder.py`.

## Pod-Level Isolation

| Control                  | Setting                                              | Purpose                                                                                                              |
|--------------------------|------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| User namespace isolation | `host_users: false`                                  | Remaps container UIDs to unprivileged host UIDs — even if a process escapes the container, it has no host privileges |
| Runtime class            | `runtime_class_name` (configurable, e.g. `"gvisor"`) | Sandboxed execution via an alternative OCI runtime. Set via `K8S_POD_RUNTIME_CLASS_NAME` in settings                 |
| Active deadline          | `active_deadline_seconds`                            | Hard timeout at the K8s level — the kubelet kills the pod regardless of what the process is doing                    |
| Restart policy           | `Never`                                              | Pods are one-shot executors; no restart loops                                                                        |
| Script injection         | ConfigMap volume mount                               | Script content is mounted read-only via a ConfigMap, not written to the container filesystem                         |

## Namespace-Level Controls

Applied automatically at k8s_worker startup via `ensure_namespace_security()` in
`backend/app/services/k8s_worker/worker.py`. These are idempotent (create-or-update).

### Network Policy

A default-deny NetworkPolicy blocks all ingress and egress traffic from executor pods — preventing lateral movement
within the cluster and data exfiltration to external hosts.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: executor-deny-all
  namespace: integr8scode
  labels:
    app: integr8s
    component: security
spec:
  podSelector:
    matchLabels:
      component: executor
  policyTypes:
    - Ingress
    - Egress
  ingress: [ ]
  egress: [ ]
```

This policy matches pods with the `component: executor` label, which the pod builder applies to all executor pods.

### Resource Quota

A ResourceQuota caps aggregate resource consumption in the executor namespace:

| Resource          | Limit                             | Derivation                       |
|-------------------|-----------------------------------|----------------------------------|
| `pods`            | `K8S_MAX_CONCURRENT_PODS`         | Maximum concurrent executor pods |
| `requests.cpu`    | `K8S_MAX_CONCURRENT_PODS` cores   | 1 core per pod                   |
| `requests.memory` | `K8S_MAX_CONCURRENT_PODS × 128Mi` | 128Mi per pod                    |
| `limits.cpu`      | Same as requests                  | Prevents burst beyond quota      |
| `limits.memory`   | Same as requests                  | Prevents OOM beyond quota        |

This prevents a burst of executions from starving other workloads in the cluster.

### Pod Security Admission (PSA)

The executor namespace is labeled with the **restricted** Pod Security Standard:

```yaml
metadata:
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/audit: restricted
```

This is a Kubernetes-native admission control (no webhook required). Pods that violate the restricted profile (e.g.,
requesting privileged mode, host networking, or writable root filesystem) are rejected at admission time.

## CNI Requirements

The NetworkPolicy requires a CNI plugin that supports network policies (Calico, Cilium, Weave Net, etc). K3s includes
Flannel by default, which does not enforce policies. For production, install a policy-capable CNI or use K3s with the
`--flannel-backend=none` flag and a separate CNI.

To allow specific egress traffic (for example, to internal services), create an additional NetworkPolicy with explicit
egress rules rather than modifying the deny-all policy.
