import logging
from typing import Any

from app.domain.enums.notification import NotificationSeverity
from app.schemas_pydantic.grafana import GrafanaAlertItem, GrafanaWebhook
from app.services.notification_service import NotificationService


class GrafanaAlertProcessor:
    """Processes Grafana alerts with reduced complexity."""

    SEVERITY_MAPPING = {
        "critical": NotificationSeverity.HIGH,
        "error": NotificationSeverity.HIGH,
        "warning": NotificationSeverity.MEDIUM,
        "info": NotificationSeverity.LOW,
    }

    RESOLVED_STATUSES = {"ok", "resolved"}
    DEFAULT_SEVERITY = "warning"
    DEFAULT_TITLE = "Grafana Alert"
    DEFAULT_MESSAGE = "Alert triggered"

    def __init__(self, notification_service: NotificationService, logger: logging.Logger) -> None:
        """Initialize the processor with required services."""
        self.notification_service = notification_service
        self.logger = logger
        self.logger.info("GrafanaAlertProcessor initialized")

    @classmethod
    def extract_severity(cls, alert: GrafanaAlertItem, webhook: GrafanaWebhook) -> str:
        """Extract severity from alert or webhook labels."""
        alert_severity = (alert.labels or {}).get("severity")
        webhook_severity = (webhook.commonLabels or {}).get("severity")
        return (alert_severity or webhook_severity or cls.DEFAULT_SEVERITY).lower()

    @classmethod
    def map_severity(cls, severity_str: str, alert_status: str | None) -> NotificationSeverity:
        """Map string severity to enum, considering alert status."""
        if alert_status and alert_status.lower() in cls.RESOLVED_STATUSES:
            return NotificationSeverity.LOW
        return cls.SEVERITY_MAPPING.get(severity_str, NotificationSeverity.MEDIUM)

    @classmethod
    def extract_title(cls, alert: GrafanaAlertItem) -> str:
        """Extract title from alert labels or annotations."""
        return (alert.labels or {}).get("alertname") or (alert.annotations or {}).get("title") or cls.DEFAULT_TITLE

    @classmethod
    def build_message(cls, alert: GrafanaAlertItem) -> str:
        """Build notification message from alert annotations."""
        annotations = alert.annotations or {}
        summary = annotations.get("summary")
        description = annotations.get("description")

        parts = [p for p in [summary, description] if p]
        if parts:
            return "\n\n".join(parts)
        return summary or description or cls.DEFAULT_MESSAGE

    @classmethod
    def build_metadata(cls, alert: GrafanaAlertItem, webhook: GrafanaWebhook, severity: str) -> dict[str, Any]:
        """Build metadata dictionary for the notification."""
        return {
            "grafana_status": alert.status or webhook.status,
            "severity": severity,
            **(webhook.commonLabels or {}),
            **(alert.labels or {}),
        }

    async def process_single_alert(
        self,
        alert: GrafanaAlertItem,
        webhook: GrafanaWebhook,
        correlation_id: str,
    ) -> tuple[bool, str | None]:
        """Process a single Grafana alert.

        Args:
            alert: The Grafana alert to process
            webhook: The webhook payload containing common data
            correlation_id: Correlation ID for tracing

        Returns:
            Tuple of (success, error_message)
        """
        try:
            severity_str = self.extract_severity(alert, webhook)
            severity = self.map_severity(severity_str, alert.status)
            title = self.extract_title(alert)
            message = self.build_message(alert)
            metadata = self.build_metadata(alert, webhook, severity_str)

            await self.notification_service.create_system_notification(
                title=title,
                message=message,
                severity=severity,
                tags=["external_alert", "grafana", "entity:external_alert"],
                metadata=metadata,
            )
            return True, None

        except Exception as e:
            error_msg = f"Failed to process Grafana alert: {e}"
            self.logger.error(error_msg, extra={"correlation_id": correlation_id}, exc_info=True)
            return False, error_msg

    async def process_webhook(self, webhook_payload: GrafanaWebhook, correlation_id: str) -> tuple[int, list[str]]:
        """Process all alerts in a Grafana webhook.

        Args:
            webhook_payload: The Grafana webhook payload
            correlation_id: Correlation ID for tracing

        Returns:
            Tuple of (processed_count, errors)
        """
        alerts = webhook_payload.alerts or []
        errors: list[str] = []
        processed_count = 0

        self.logger.info(
            "Processing Grafana webhook",
            extra={
                "correlation_id": correlation_id,
                "status": webhook_payload.status,
                "alerts_count": len(alerts),
            },
        )

        for alert in alerts:
            success, error_msg = await self.process_single_alert(alert, webhook_payload, correlation_id)
            if success:
                processed_count += 1
            elif error_msg:
                errors.append(error_msg)

        self.logger.info(
            "Grafana webhook processing completed",
            extra={
                "correlation_id": correlation_id,
                "alerts_received": len(alerts),
                "alerts_processed": processed_count,
                "errors_count": len(errors),
            },
        )

        return processed_count, errors
