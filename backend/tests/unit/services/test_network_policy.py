from app.services.network_policy import NetworkPolicyBuilder


class TestNetworkPolicy:

    def test_network_policy_builder_complete(self) -> None:
        execution_id = "test-execution-id"
        namespace = "test-namespace"

        builder = NetworkPolicyBuilder(execution_id, namespace)
        policy = builder.build()

        # Verify the complete policy structure
        assert policy["apiVersion"] == "networking.k8s.io/v1"
        assert policy["kind"] == "NetworkPolicy"

        # Verify metadata
        metadata = policy["metadata"]
        assert metadata["name"] == f"deny-external-{execution_id}"
        assert metadata["namespace"] == namespace
        assert metadata["labels"]["execution-id"] == execution_id

        # Verify spec
        spec = policy["spec"]
        assert "podSelector" in spec
        assert spec["podSelector"]["matchLabels"]["execution-id"] == execution_id
        assert spec["policyTypes"] == ["Ingress", "Egress"]

        # Verify ingress and egress are empty arrays (default deny all)
        assert spec["ingress"] == []
        assert spec["egress"] == []

    def test_network_policy_builder_different_values(self) -> None:
        """Test NetworkPolicyBuilder with different execution IDs and namespaces"""
        test_cases = [
            ("exec-1", "default"),
            ("my-execution-123", "production"),
            ("test-exec", "staging")
        ]

        for execution_id, namespace in test_cases:
            builder = NetworkPolicyBuilder(execution_id, namespace)
            policy = builder.build()

            assert policy["metadata"]["name"] == f"deny-external-{execution_id}"
            assert policy["metadata"]["namespace"] == namespace
            assert policy["metadata"]["labels"]["execution-id"] == execution_id
            assert policy["spec"]["podSelector"]["matchLabels"]["execution-id"] == execution_id
