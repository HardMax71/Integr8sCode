from typing import Any

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter

from app.core.correlation import CorrelationContext
from app.core.logging import logger
from app.domain.enums.notification import NotificationSeverity
from app.schemas_pydantic.grafana import AlertResponse, GrafanaWebhook
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/alerts", tags=["alerts"], route_class=DishkaRoute)


@router.post("/grafana", response_model=AlertResponse)
async def receive_grafana_alerts(
    webhook_payload: GrafanaWebhook,
    notification_service: FromDishka[NotificationService],
) -> AlertResponse:
    correlation_id = CorrelationContext.get_correlation_id()

    logger.info(
        "Received Grafana alert webhook",
        extra={
            "correlation_id": correlation_id,
            "status": webhook_payload.status,
            "alerts_count": len(webhook_payload.alerts or []),
        },
    )

    errors: list[str] = []
    processed_count = 0

    alerts = webhook_payload.alerts or []
    for alert in alerts:
        try:
            # Severity resolution
            sev = (
                (alert.labels or {}).get("severity")
                or (webhook_payload.commonLabels or {}).get("severity")
                or "warning"
            ).lower()

            # Severity mapping
            if sev in ("critical", "error"):
                severity = NotificationSeverity.HIGH
            elif alert.status and alert.status.lower() in ("ok", "resolved"):
                severity = NotificationSeverity.LOW
            else:
                severity = NotificationSeverity.MEDIUM

            title = (
                (alert.labels or {}).get("alertname")
                or (alert.annotations or {}).get("title")
                or "Grafana Alert"
            )
            summary = (alert.annotations or {}).get("summary")
            description = (alert.annotations or {}).get("description")
            message_parts = [p for p in [summary, description] if p]
            message = "\n\n".join(message_parts) if message_parts else (summary or description or "Alert triggered")

            metadata: dict[str, Any] = {
                "grafana_status": alert.status or webhook_payload.status,
                "severity": sev,
                **(webhook_payload.commonLabels or {}),
                **(alert.labels or {}),
            }

            await notification_service.create_system_notification(
                title=title,
                message=message,
                severity=severity,
                tags=["external_alert", "grafana", "entity:external_alert"],
                metadata=metadata,
            )
            processed_count += 1
        except Exception as e:  # keep one alert failure from impacting others
            err = f"Failed to process Grafana alert: {e}"
            errors.append(err)
            logger.error(err, extra={"correlation_id": correlation_id}, exc_info=True)

    logger.info(
        "Grafana webhook processing completed",
        extra={
            "correlation_id": correlation_id,
            "alerts_received": len(alerts),
            "alerts_processed": processed_count,
            "errors_count": len(errors),
        },
    )

    return AlertResponse(
        message="Webhook received and processed",
        alerts_received=len(alerts),
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
