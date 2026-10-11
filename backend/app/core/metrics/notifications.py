from app.core.metrics.base import BaseMetrics


class NotificationMetrics(BaseMetrics):
    """Metrics for notifications."""

    def _create_instruments(self) -> None:
        self.notifications_sent = self._meter.create_counter(
            name="notifications.sent.total", description="Total number of notifications sent", unit="1"
        )

        self.notifications_failed = self._meter.create_counter(
            name="notifications.failed.total", description="Total number of failed notifications", unit="1"
        )

        self.notification_delivery_time = self._meter.create_histogram(
            name="notification.delivery.time", description="Time taken to deliver notifications in seconds", unit="s"
        )

        self.notifications_by_channel = self._meter.create_counter(
            name="notifications.by.channel.total", description="Total notifications sent by channel", unit="1"
        )

        self.channel_delivery_time = self._meter.create_histogram(
            name="notification.channel.delivery.time", description="Delivery time by channel in seconds", unit="s"
        )

        self.channel_failures = self._meter.create_counter(
            name="notification.channel.failures.total", description="Total failures by channel", unit="1"
        )

        self.notifications_by_severity = self._meter.create_counter(
            name="notifications.by.severity.total", description="Total notifications by severity level", unit="1"
        )

        self.notifications_throttled = self._meter.create_counter(
            name="notifications.throttled.total", description="Total notifications throttled", unit="1"
        )

        self.notification_retries = self._meter.create_counter(
            name="notification.retries.total",
            description="Delivery attempts that failed and were retried",
            unit="1",
        )

        self.subscription_changes = self._meter.create_counter(
            name="notification.subscription.changes.total", description="Total subscription changes", unit="1"
        )

    def record_notification_sent(
        self, notification_type: str, channel: str = "in_app", severity: str = "medium"
    ) -> None:
        self.notifications_sent.add(1, attributes={"category": notification_type})
        self.notifications_by_channel.add(1, attributes={"channel": channel, "category": notification_type})
        self.notifications_by_severity.add(1, attributes={"severity": severity, "category": notification_type})

    def record_notification_failed(self, notification_type: str, error: str, channel: str = "in_app") -> None:
        self.notifications_failed.add(1, attributes={"category": notification_type, "error": error})
        self.channel_failures.add(1, attributes={"channel": channel, "error": error})

    def record_notification_delivery_time(
        self, duration_seconds: float, notification_type: str, channel: str = "in_app"
    ) -> None:
        self.notification_delivery_time.record(duration_seconds, attributes={"category": notification_type})
        self.channel_delivery_time.record(
            duration_seconds, attributes={"channel": channel, "category": notification_type}
        )

    def record_notification_throttled(self, notification_type: str) -> None:
        self.notifications_throttled.add(1, attributes={"category": notification_type})

    def record_notification_retry(self, notification_type: str, channel: str) -> None:
        self.notification_retries.add(1, attributes={"category": notification_type, "channel": channel})

    def record_subscription_change(self, channel: str, enabled: bool | None) -> None:
        action = "enabled" if enabled is True else "disabled" if enabled is False else "updated"
        self.subscription_changes.add(
            1,
            attributes={
                "channel": channel,
                "action": action,
            },
        )
