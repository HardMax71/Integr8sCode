# Pod and namespace security

User code runs in executor pods in the `integr8scode` namespace. The pod builder locks down each pod, the k8s worker locks down the namespace at startup, and Kueue caps how much the namespace can use in total.

## Executor pods

[`pod_builder.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/services/k8s_worker/pod_builder.py) builds every executor pod the same way. The container runs as UID and GID 1000 with `runAsNonRoot`, a read-only root filesystem, `allowPrivilegeEscalation: false`, all capabilities dropped and the `RuntimeDefault` seccomp profile.

| Setting                          | Value                                    | Why                                                       |
|----------------------------------|------------------------------------------|-----------------------------------------------------------|
| `hostUsers`                      | `false`                                  | user namespaces: container UIDs map to unprivileged host UIDs |
| `automountServiceAccountToken`   | `false`                                  | no token, so no Kubernetes API access                     |
| `enableServiceLinks`             | `false`                                  | no service env vars to discover the cluster               |
| `hostNetwork`, `hostPID`, `hostIPC` | `false`                               | no host namespaces                                        |
| `restartPolicy`                  | `Never`                                  | one-shot pods                                             |
| `activeDeadlineSeconds`          | the execution timeout, at least the language minimum | the kubelet kills the pod at the deadline        |
| `runtimeClassName`               | `K8S_POD_RUNTIME_CLASS_NAME`, unset by default | lets you run pods under gVisor or another sandbox   |

The script and `entrypoint.sh` come from a per-execution ConfigMap, mounted read-only. The only writable paths are two `emptyDir` volumes: `/output` (10Mi) and `/tmp` (10Mi, or more for languages that need it).

The timeout is the admin setting `max_timeout_seconds`, which falls back to `K8S_POD_EXECUTION_TIMEOUT` (5 seconds in `config.toml`). CPU and memory limits come from `K8S_POD_CPU_LIMIT` and `K8S_POD_MEMORY_LIMIT`. A language can raise all three through its `PodRuntimeConfig` in `runtime_registry.py`. Today only Go does: at least 1000m CPU, 320Mi memory, 30 seconds and a 64Mi `/tmp` for its build cache.

## Namespace

The k8s worker calls `ensure_namespace_security()` when it starts. Both steps are server-side applies, so they're safe to repeat.

The first creates or updates the `executor-deny-all` NetworkPolicy. It selects pods labelled `component: executor`, which every executor pod has, and denies all ingress and egress. The worker is the only owner of this policy; `setup-k8s.sh` doesn't create it.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: executor-deny-all
  namespace: integr8scode
  labels: {app: integr8s, component: security}
spec:
  podSelector:
    matchLabels: {component: executor}
  policyTypes: [Ingress, Egress]
  ingress: []
  egress: []
```

The second labels the namespace with the `restricted` Pod Security Standard for `enforce`, `warn` and `audit`. The API server then rejects any pod that asks for privileges the profile forbids.

The worker also applies a `runtime-image-pre-puller` DaemonSet that pulls every runtime image onto each node, so executor pods don't wait on a pull. Its containers also follow the restricted profile.

The worker reaches the cluster with the `integr8scode-sa` service account that `setup-k8s.sh` creates. `setup-k8s.sh` also writes the kubeconfig with that account's token. A Role in the namespace lets it manage pods (with logs and exec), ConfigMaps, services, DaemonSets and NetworkPolicies, and a ClusterRole lets it get, list and patch namespaces for the labels.

## Quota with Kueue

Kueue enforces the namespace's total CPU and memory, not the worker and not a ResourceQuota. `setup-k8s.sh` installs Kueue v0.20.1 (manifest checked by SHA256) and creates the queues:

| Resource       | Name             | Purpose                                        |
|----------------|------------------|------------------------------------------------|
| ResourceFlavor | `default-flavor` | the cluster's default resources                |
| ClusterQueue   | `executor-queue` | quota of 32 CPU and 4Gi memory                 |
| LocalQueue     | `executor-queue` | queue in `integr8scode`, bound to the ClusterQueue |

Executor pods carry `kueue.x-k8s.io/queue-name: executor-queue`. When the quota is used up, Kueue holds new pods behind a scheduling gate instead of rejecting them the way a ResourceQuota would, and releases them as quota frees up. `activeDeadlineSeconds` only starts once a pod is running on a node, so time spent gated doesn't eat into the execution timeout. How many executions run at once is still decided by the saga orchestrator's queue; Kueue is the backstop for total resource use.

## Network policy enforcement

A NetworkPolicy only works if something enforces it. k3s does, through its embedded network policy controller, unless it was started with `--disable-network-policy`. On other clusters you need a CNI that enforces policies, such as Calico or Cilium; plain Flannel doesn't.

To let executors reach something specific, add a separate NetworkPolicy with explicit egress rules instead of editing `executor-deny-all`. The worker would overwrite your edit on its next start anyway.
