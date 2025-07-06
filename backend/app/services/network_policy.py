from typing import Any, Dict


class NetworkPolicyBuilder:
    def __init__(self, execution_id: str, namespace: str = "default"):
        self.execution_id = execution_id
        self.namespace = namespace

    def build(self) -> Dict[str, Any]:
        return {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {
                "name": f"deny-external-{self.execution_id}",
                "namespace": self.namespace,
                "labels": {
                    "app": "script-execution",
                    "execution-id": self.execution_id
                }
            },
            "spec": {
                "podSelector": {
                    "matchLabels": {
                        "execution-id": self.execution_id
                    }
                },
                "policyTypes": ["Ingress", "Egress"],
                "ingress": [],
                "egress": []
            }
        }
