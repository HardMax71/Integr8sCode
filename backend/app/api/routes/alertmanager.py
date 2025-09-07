from typing import Any, Dict

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, BackgroundTasks

from app.core.correlation import CorrelationContext
from app.core.logging import logger
from app.domain.enums.user import UserRole
from app.schemas_pydantic.alertmanager import AlertmanagerWebhook, AlertResponse
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/alertmanager",
                   tags=["alertmanager"],
                   route_class=DishkaRoute)


@router.post("/webhook", response_model=AlertResponse)
async def receive_alerts(
        webhook_payload: AlertmanagerWebhook,
        background_tasks: BackgroundTasks,
        notification_service: FromDishka[NotificationService]
) -> AlertResponse:
    correlation_id = CorrelationContext.get_correlation_id()

    logger.info(
        "Received Alertmanager webhook",
        extra={
            "correlation_id": correlation_id,
            "receiver": webhook_payload.receiver,
            "status": webhook_payload.status,
            "alerts_count": len(webhook_payload.alerts),
            "group_key": webhook_payload.group_key,
            "group_labels": webhook_payload.group_labels
        }
    )

    errors: list[str] = []
    processed_count = 0

    # Process each alert
    for alert in webhook_payload.alerts:
        try:
            # Determine severity from labels
            severity = alert.labels.get("severity", "warning")
            alert_name = alert.labels.get("alertname", "Unknown Alert")

            # Create notification message
            title = f"🚨 Alert: {alert_name}"
            if alert.status == "resolved":
                title = f"✅ Resolved: {alert_name}"

            message = alert.annotations.get("summary", "Alert triggered")
            description = alert.annotations.get("description", "")

            if description:
                message = f"{message}\n\n{description}"

            # Add labels info
            labels_text = "\n".join(
                [f"{k}: {v}" for k, v in alert.labels.items() if k not in ["alertname", "severity"]])
            if labels_text:
                message = f"{message}\n\nLabels:\n{labels_text}"

            # Map severity to notification type
            notification_type = "error" if severity in ["critical", "error"] else "warning"
            if alert.status == "resolved":
                notification_type = "success"

            # Create system-wide notification
            background_tasks.add_task(
                notification_service.create_system_notification,
                title=title,
                message=message,
                notification_type=notification_type,
                metadata={
                    "alert_fingerprint": alert.fingerprint,
                    "alert_status": alert.status,
                    "severity": severity,
                    "generator_url": alert.generator_url,
                    "starts_at": alert.starts_at,
                    "ends_at": alert.ends_at,
                    "receiver": webhook_payload.receiver,
                    "group_key": webhook_payload.group_key,
                    "correlation_id": correlation_id
                },
                # For critical alerts, notify all active users
                # For other alerts, notify only admin and moderator users
                target_roles=[UserRole.ADMIN, UserRole.MODERATOR] if severity not in ["critical", "error"] else None
            )

            processed_count += 1

            logger.info(
                f"Processing alert: {alert_name}",
                extra={
                    "correlation_id": correlation_id,
                    "alert_fingerprint": alert.fingerprint,
                    "alert_status": alert.status,
                    "severity": severity,
                    "starts_at": alert.starts_at
                }
            )

        except Exception as e:
            error_msg = f"Failed to process alert {alert.fingerprint}: {str(e)}"
            errors.append(error_msg)
            logger.error(
                error_msg,
                extra={
                    "correlation_id": correlation_id,
                    "alert_fingerprint": alert.fingerprint,
                    "error": str(e)
                },
                exc_info=True
            )

    # Log final status
    logger.info(
        "Alertmanager webhook processing completed",
        extra={
            "correlation_id": correlation_id,
            "alerts_received": len(webhook_payload.alerts),
            "alerts_processed": processed_count,
            "errors_count": len(errors)
        }
    )

    return AlertResponse(
        message="Webhook received and processed",
        alerts_received=len(webhook_payload.alerts),
        alerts_processed=processed_count,
        errors=errors
    )


@router.get("/test")
async def test_alertmanager_endpoint() -> Dict[str, Any]:
    """Test endpoint to verify Alertmanager route is accessible"""
    return {
        "status": "ok",
        "message": "Alertmanager webhook endpoint is ready",
        "webhook_url": "/api/v1/alertmanager/webhook"
    }
