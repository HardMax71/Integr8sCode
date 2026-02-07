import pytest
from app.schemas_pydantic.grafana import AlertResponse
from httpx import AsyncClient

pytestmark = [pytest.mark.e2e]


class TestGrafanaWebhook:
    """Tests for POST /api/v1/alerts/grafana."""

    @pytest.mark.asyncio
    async def test_receive_grafana_alert(self, client: AsyncClient) -> None:
        """Receive a Grafana alert webhook."""
        response = await client.post(
            "/api/v1/alerts/grafana",
            json={
                "status": "firing",
                "receiver": "integr8s-receiver",
                "alerts": [
                    {
                        "status": "firing",
                        "labels": {
                            "alertname": "HighCPUUsage",
                            "severity": "critical",
                            "instance": "worker-1",
                        },
                        "annotations": {
                            "summary": "High CPU usage detected",
                            "description": "CPU usage is above 90%",
                        },
                        "valueString": "95%",
                    }
                ],
                "groupLabels": {
                    "alertname": "HighCPUUsage",
                },
                "commonLabels": {
                    "severity": "critical",
                },
                "commonAnnotations": {
                    "summary": "High CPU usage detected",
                },
            },
        )

        assert response.status_code == 200
        result = AlertResponse.model_validate(response.json())

        assert result.message
        assert result.alerts_received == 1
        assert result.alerts_processed == 1
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_receive_multiple_grafana_alerts(
        self, client: AsyncClient
    ) -> None:
        """Receive multiple alerts in one webhook."""
        response = await client.post(
            "/api/v1/alerts/grafana",
            json={
                "status": "firing",
                "receiver": "integr8s-receiver",
                "alerts": [
                    {
                        "status": "firing",
                        "labels": {"alertname": "Alert1", "severity": "warning"},
                        "annotations": {"summary": "Alert 1"},
                    },
                    {
                        "status": "firing",
                        "labels": {"alertname": "Alert2", "severity": "critical"},
                        "annotations": {"summary": "Alert 2"},
                    },
                    {
                        "status": "resolved",
                        "labels": {"alertname": "Alert3", "severity": "info"},
                        "annotations": {"summary": "Alert 3"},
                    },
                ],
                "groupLabels": {},
                "commonLabels": {},
                "commonAnnotations": {},
            },
        )

        assert response.status_code == 200
        result = AlertResponse.model_validate(response.json())

        assert result.alerts_received == 3
        assert result.alerts_processed == 3

    @pytest.mark.asyncio
    async def test_receive_grafana_alert_resolved(
        self, client: AsyncClient
    ) -> None:
        """Receive a resolved alert."""
        response = await client.post(
            "/api/v1/alerts/grafana",
            json={
                "status": "resolved",
                "receiver": "integr8s-receiver",
                "alerts": [
                    {
                        "status": "resolved",
                        "labels": {
                            "alertname": "HighMemoryUsage",
                            "severity": "warning",
                        },
                        "annotations": {
                            "summary": "Memory usage back to normal",
                        },
                    }
                ],
                "groupLabels": {},
                "commonLabels": {},
                "commonAnnotations": {},
            },
        )

        assert response.status_code == 200
        result = AlertResponse.model_validate(response.json())
        assert result.alerts_received == 1

    @pytest.mark.asyncio
    async def test_receive_grafana_alert_empty_alerts(
        self, client: AsyncClient
    ) -> None:
        """Receive webhook with empty alerts list."""
        response = await client.post(
            "/api/v1/alerts/grafana",
            json={
                "status": "firing",
                "receiver": "integr8s-receiver",
                "alerts": [],
                "groupLabels": {},
                "commonLabels": {},
                "commonAnnotations": {},
            },
        )

        assert response.status_code == 200
        result = AlertResponse.model_validate(response.json())
        assert result.alerts_received == 0
        assert result.alerts_processed == 0

    @pytest.mark.asyncio
    async def test_receive_grafana_alert_minimal_payload(
        self, client: AsyncClient
    ) -> None:
        """Receive webhook with minimal payload."""
        response = await client.post(
            "/api/v1/alerts/grafana",
            json={
                "alerts": [
                    {
                        "labels": {"alertname": "MinimalAlert"},
                    }
                ],
            },
        )

        assert response.status_code == 200
        result = AlertResponse.model_validate(response.json())
        assert result.alerts_received == 1

    @pytest.mark.asyncio
    async def test_receive_grafana_alert_with_value_string(
        self, client: AsyncClient
    ) -> None:
        """Receive alert with valueString field."""
        response = await client.post(
            "/api/v1/alerts/grafana",
            json={
                "status": "firing",
                "alerts": [
                    {
                        "status": "firing",
                        "labels": {
                            "alertname": "DiskSpaceLow",
                            "instance": "server-1",
                        },
                        "annotations": {
                            "summary": "Disk space is running low",
                        },
                        "valueString": "10% available",
                    }
                ],
            },
        )

        assert response.status_code == 200
        result = AlertResponse.model_validate(response.json())
        assert result.alerts_received == 1


class TestGrafanaTestEndpoint:
    """Tests for GET /api/v1/alerts/grafana/test."""

    @pytest.mark.asyncio
    async def test_grafana_test_endpoint(self, client: AsyncClient) -> None:
        """Test the Grafana webhook test endpoint."""
        response = await client.get("/api/v1/alerts/grafana/test")

        assert response.status_code == 200
        result = response.json()

        assert result["status"] == "ok"
        assert "message" in result
        assert "webhook_url" in result
        assert result["webhook_url"] == "/api/v1/alerts/grafana"

    @pytest.mark.asyncio
    async def test_grafana_test_endpoint_as_user(
        self, test_user: AsyncClient
    ) -> None:
        """Authenticated user can access test endpoint."""
        response = await test_user.get("/api/v1/alerts/grafana/test")

        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_grafana_test_endpoint_as_admin(
        self, test_admin: AsyncClient
    ) -> None:
        """Admin can access test endpoint."""
        response = await test_admin.get("/api/v1/alerts/grafana/test")

        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "ok"
        assert "Grafana webhook endpoint is ready" in result["message"]
