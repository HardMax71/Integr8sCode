import httpx
import pytest
from datetime import datetime, timezone


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_grafana_alert_endpoints(client: httpx.AsyncClient) -> None:
    # Test endpoint
    r_test = await client.get("/api/v1/alerts/grafana/test")
    assert r_test.status_code == 200
    assert "webhook_url" in r_test.json()

    # Webhook minimal payload
    payload = {
        "receiver": "it",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "IT Test", "severity": "warning"},
                "annotations": {"summary": "Sum", "description": "Desc"},
                "startsAt": datetime.now(timezone.utc).isoformat(),
                "endsAt": datetime.now(timezone.utc).isoformat(),
                "generatorURL": "http://example",
                "fingerprint": "abc123",
            }
        ],
        "groupLabels": {},
        "commonLabels": {},
        "commonAnnotations": {},
        "externalURL": "http://am",
        "version": "4",
        "groupKey": "{}:{}",
    }
    r_webhook = await client.post("/api/v1/alerts/grafana", json=payload)
    assert r_webhook.status_code == 200
    body = r_webhook.json()
    assert body.get("alerts_received") == 1
