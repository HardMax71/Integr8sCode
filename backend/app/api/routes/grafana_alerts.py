from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter

from app.core.correlation import CorrelationContext
from app.schemas_pydantic.grafana import AlertResponse, GrafanaWebhook
from app.services.grafana_alert_processor import GrafanaAlertProcessor

router = APIRouter(prefix="/alerts", tags=["alerts"], route_class=DishkaRoute)


@router.post("/grafana", response_model=AlertResponse)
async def receive_grafana_alerts(
    webhook_payload: GrafanaWebhook,
    processor: FromDishka[GrafanaAlertProcessor],
) -> AlertResponse:
    correlation_id = CorrelationContext.get_correlation_id()

    processed_count, errors = await processor.process_webhook(webhook_payload, correlation_id)

    alerts_count = len(webhook_payload.alerts or [])

    return AlertResponse(
        message="Webhook received and processed",
        alerts_received=alerts_count,
        alerts_processed=processed_count,
        errors=errors,
    )


@router.get("/grafana/test")
async def test_grafana_alert_endpoint() -> dict[str, str]:
    return {
        "status": "ok",
        "message": "Grafana webhook endpoint is ready",
        "webhook_url": "/api/v1/alerts/grafana",
    }
