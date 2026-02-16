from app.core.metrics.base import BaseMetrics


class NotificationMetrics(BaseMetrics):
    """Metrics for notifications."""

    def _create_instruments(self) -> None:
        # Core notification metrics
        self.notifications_sent = self._meter.create_counter(
            name="notifications.sent.total", description="Total number of notifications sent", unit="1"
        )

        self.notifications_failed = self._meter.create_counter(
            name="notifications.failed.total", description="Total number of failed notifications", unit="1"
        )

        self.notification_delivery_time = self._meter.create_histogram(
            name="notification.delivery.time", description="Time taken to deliver notifications in seconds", unit="s"
        )

        # Channel-specific metrics
        self.notifications_by_channel = self._meter.create_counter(
            name="notifications.by.channel.total", description="Total notifications sent by channel", unit="1"
        )

        self.channel_delivery_time = self._meter.create_histogram(
            name="notification.channel.delivery.time", description="Delivery time by channel in seconds", unit="s"
        )

        self.channel_failures = self._meter.create_counter(
            name="notification.channel.failures.total", description="Total failures by channel", unit="1"
        )

        # Severity metrics
        self.notifications_by_severity = self._meter.create_counter(
            name="notifications.by.severity.total", description="Total notifications by severity level", unit="1"
        )

        # Status tracking
        self.notification_status_changes = self._meter.create_counter(
            name="notification.status.changes.total", description="Total notification status changes", unit="1"
        )

        self.notifications_pending = self._meter.create_up_down_counter(
            name="notifications.pending", description="Number of pending notifications", unit="1"
        )

        self.notifications_queued = self._meter.create_up_down_counter(
            name="notifications.queued", description="Number of queued notifications", unit="1"
        )

        # User engagement metrics
        self.notifications_read = self._meter.create_counter(
            name="notifications.read.total", description="Total notifications read by users", unit="1"
        )

        self.unread_count = self._meter.create_up_down_counter(
            name="notifications.unread.count", description="Current unread notifications per user", unit="1"
        )

        # Throttling metrics
        self.notifications_throttled = self._meter.create_counter(
            name="notifications.throttled.total", description="Total notifications throttled", unit="1"
        )

        self.throttle_window_hits = self._meter.create_counter(
            name="notification.throttle.window.hits.total",
            description="Number of times throttle window was hit",
            unit="1",
        )

        # Retry metrics
        self.notification_retries = self._meter.create_counter(
            name="notification.retries.total", description="Total notification retry attempts", unit="1"
        )

        self.retry_success_rate = self._meter.create_histogram(
            name="notification.retry.success.rate", description="Success rate of retried notifications", unit="%"
        )

        # Webhook-specific metrics
        self.webhook_delivery_time = self._meter.create_histogram(
            name="notification.webhook.delivery.time",
            description="Time to deliver webhook notifications in seconds",
            unit="s",
        )

        self.webhook_response_status = self._meter.create_counter(
            name="notification.webhook.response.status.total", description="Webhook response status codes", unit="1"
        )

        # Slack-specific metrics
        self.slack_delivery_time = self._meter.create_histogram(
            name="notification.slack.delivery.time",
            description="Time to deliver Slack notifications in seconds",
            unit="s",
        )

        self.slack_api_errors = self._meter.create_counter(
            name="notification.slack.api.errors.total", description="Total Slack API errors", unit="1"
        )

        # Subscription metrics
        self.subscriptions_active = self._meter.create_up_down_counter(
            name="notification.subscriptions.active",
            description="Number of active notification subscriptions",
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

    def record_notification_status_change(self, notification_id: str, from_status: str, to_status: str) -> None:
        self.notification_status_changes.add(1, attributes={"from_status": from_status, "to_status": to_status})

        if from_status == "pending":
            self.notifications_pending.add(-1)
        if to_status == "pending":
            self.notifications_pending.add(1)

        if from_status == "queued":
            self.notifications_queued.add(-1)
        if to_status == "queued":
            self.notifications_queued.add(1)

    def record_notification_read(self, notification_type: str) -> None:
        self.notifications_read.add(1, attributes={"category": notification_type})

    def decrement_unread_count(self, user_id: str) -> None:
        self.unread_count.add(-1, attributes={"user_id": user_id})

    def record_notification_throttled(self, notification_type: str, user_id: str) -> None:
        self.notifications_throttled.add(1, attributes={"category": notification_type, "user_id": user_id})

    def record_throttle_window_hit(self, user_id: str) -> None:
        self.throttle_window_hits.add(1, attributes={"user_id": user_id})

    def record_notification_retry(self, notification_type: str, attempt_number: int, success: bool) -> None:
        self.notification_retries.add(
            1, attributes={"category": notification_type, "attempt": str(attempt_number), "success": str(success)}
        )

        if attempt_number > 1:
            self.retry_success_rate.record(100.0 if success else 0.0, attributes={"category": notification_type})

    def record_webhook_delivery(self, duration_seconds: float, status_code: int, url_pattern: str) -> None:
        self.webhook_delivery_time.record(
            duration_seconds, attributes={"status_code": str(status_code), "url_pattern": url_pattern}
        )
        self.webhook_response_status.add(1, attributes={"status_code": str(status_code), "url_pattern": url_pattern})

    def record_slack_delivery(
        self, duration_seconds: float, channel: str, success: bool, error_type: str | None = None
    ) -> None:
        self.slack_delivery_time.record(duration_seconds, attributes={"channel": channel, "success": str(success)})

        if not success and error_type:
            self.slack_api_errors.add(1, attributes={"error_type": error_type, "channel": channel})

    def update_active_subscriptions(self, user_id: str, count: int) -> None:
        key = f"_subscriptions_{user_id}"
        current_val = getattr(self, key, 0)
        delta = count - current_val
        if delta != 0:
            self.subscriptions_active.add(delta, attributes={"user_id": user_id})
        setattr(self, key, count)

    def record_subscription_change(self, user_id: str, notification_type: str, action: str) -> None:
        self.subscription_changes.add(
            1,
            attributes={
                "user_id": user_id,
                "category": notification_type,
                "action": action,
            },
        )

    def increment_pending_notifications(self) -> None:
        self.notifications_pending.add(1)

    def decrement_pending_notifications(self) -> None:
        self.notifications_pending.add(-1)

    def increment_queued_notifications(self) -> None:
        self.notifications_queued.add(1)

    def decrement_queued_notifications(self) -> None:
        self.notifications_queued.add(-1)
