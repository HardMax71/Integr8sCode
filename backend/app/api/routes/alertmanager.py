"""Alertmanager webhook endpoint for receiving alerts"""

from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Request

from app.core.correlation import CorrelationContext
from app.core.logging import logger
from app.core.service_dependencies import NotificationServiceDep
from app.schemas_pydantic.alertmanager import AlertmanagerWebhook, AlertResponse

router = APIRouter(prefix="/alertmanager", tags=["alertmanager"])


@router.post("/webhook", response_model=AlertResponse)
async def receive_alerts(
        webhook_payload: AlertmanagerWebhook,
        background_tasks: BackgroundTasks,
        request: Request,
        notification_service: NotificationServiceDep
) -> AlertResponse:
    """
    Receive alerts from Alertmanager webhook
    
    Args:
        webhook_payload: Alertmanager webhook payload
        background_tasks: FastAPI background tasks
        request: HTTP request
        notification_service: Notification service
        
    Returns:
        AlertResponse with processing status
    """
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
                    "starts_at": alert.starts_at.isoformat(),
                    "ends_at": alert.ends_at.isoformat() if alert.ends_at else None,
                    "receiver": webhook_payload.receiver,
                    "group_key": webhook_payload.group_key,
                    "correlation_id": correlation_id
                },
                # For critical alerts, notify all active users
                # For other alerts, notify only admin users
                target_roles=["admin", "operator"] if severity not in ["critical", "error"] else None
            )

            processed_count += 1

            logger.info(
                f"Processing alert: {alert_name}",
                extra={
                    "correlation_id": correlation_id,
                    "alert_fingerprint": alert.fingerprint,
                    "alert_status": alert.status,
                    "severity": severity,
                    "starts_at": alert.starts_at.isoformat()
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
