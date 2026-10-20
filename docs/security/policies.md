# Pod and namespace security

User code runs in executor pods in the `integr8scode` namespace. The pod builder locks down each pod, the k8s worker locks down the namespace at startup, and a ResourceQuota caps how much CPU and memory the pods can request in total.

## Executor pods

[pod_builder.py](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/services/k8s_worker/pod_builder.py) builds every executor pod the same way. The container runs as UID and GID 1000 with `runAsNonRoot`, a read-only root filesystem, `allowPrivilegeEscalation: false`, all capabilities dropped and the `RuntimeDefault` seccomp profile.

| Setting                          | Value                                    | Why                                                       |
|----------------------------------|------------------------------------------|-----------------------------------------------------------|
| `hostUsers`                      | `false`                                  | user namespaces: container UIDs map to unprivileged host UIDs |
| `automountServiceAccountToken`   | `false`                                  | no token, so no Kubernetes API access                     |
| `enableServiceLinks`             | `false`                                  | no service env vars to discover the cluster               |
| `hostNetwork`, `hostPID`, `hostIPC` | `false`                               | no host namespaces                                        |
| `restartPolicy`                  | `Never`                                  | one-shot pods                                             |
| `activeDeadlineSeconds`          | the execution timeout, at least the language minimum | the kubelet kills the pod at the deadline        |
| `runtimeClassName`               | `K8S_POD_RUNTIME_CLASS_NAME`, unset by default | lets you run pods under gVisor or another sandbox   |

The script and entrypoint.sh come from a per-execution ConfigMap, mounted read-only. The only writable paths are two `emptyDir` volumes: `/output` (10Mi) and `/tmp` (10Mi, or more for languages that need it).

The timeout and the CPU and memory limits are the admin settings `max_timeout_seconds`, `cpu_limit` and `memory_limit`. The first read stores them in MongoDB, seeded from `K8S_POD_EXECUTION_TIMEOUT` (5 seconds), `K8S_POD_CPU_LIMIT` (1000m) and `K8S_POD_MEMORY_LIMIT` (128Mi) in config.toml. After that, editing those keys changes nothing until an admin resets the settings. A language can raise all three through its `PodRuntimeConfig` in runtime_registry.py. Today only Go does: at least 1000m CPU, 320Mi memory, 30 seconds and a 64Mi `/tmp` for its build cache. Requests always come from `K8S_POD_CPU_REQUEST` (200m) and `K8S_POD_MEMORY_REQUEST` (128Mi).

## Namespace

The k8s worker calls `ensure_namespace_security()` when it starts. It server-side applies three objects, so each step is safe to repeat: the namespace with its Pod Security labels, the NetworkPolicy and the ResourceQuota.

The first creates or updates the `executor-deny-all` NetworkPolicy. It selects pods labelled `component: executor`, which every executor pod has, and denies all ingress and egress. The worker is the only owner of this policy.

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

The worker reaches the cluster with k3s's own kubeconfig, mounted read-only from `/etc/rancher/k3s` into the worker container only, so it holds the cluster's admin rights. A service account limited to the namespace would not hold it back: the worker sets the namespace's Pod Security labels itself, and an account allowed to change those labels can lift the namespace out of `restricted`. The API container mounts no kubeconfig.

## Quota

The `executor-quota` ResourceQuota caps the total CPU and memory that pods in the namespace request, not what they use: a default pod requests 200m CPU but may use up to its 1000m limit. The worker applies it with `requests.cpu` from `K8S_NAMESPACE_CPU_QUOTA` (32) and `requests.memory` from `K8S_NAMESPACE_MEMORY_QUOTA` (4Gi). The API server refuses a pod that would go over it with `403 Forbidden`, and the worker publishes `pod_creation_failed` for its execution.

How many executions run at once is decided by the execution scheduler's queue (`max_concurrent_executions`, 10 by default). Every pod requests 200m CPU and 128Mi, Go's included, since Go raises only its limits, so 10 executions request 2 CPU and 1.25Gi. The memory quota fills at 32 pods, which makes it a backstop that refuses pods only when the admin settings allow more than that at once.

## Network policy enforcement

A NetworkPolicy only works if something enforces it. k3s does, through its embedded network policy controller, unless it was started with `--disable-network-policy`. On other clusters you need a CNI that enforces policies, such as Calico or Cilium; plain Flannel doesn't.

To let executors reach something specific, add a separate NetworkPolicy with explicit egress rules instead of editing `executor-deny-all`. The worker would overwrite your edit on its next start anyway.
