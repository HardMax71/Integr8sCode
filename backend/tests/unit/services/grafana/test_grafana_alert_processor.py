import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.domain.enums.notification import NotificationSeverity
from app.schemas_pydantic.grafana import GrafanaAlertItem, GrafanaWebhook
from app.services.grafana_alert_processor import GrafanaAlertProcessor

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_notification_service() -> AsyncMock:
    """Mock notification service."""
    service = AsyncMock()
    service.create_system_notification = AsyncMock()
    return service


@pytest.fixture
def mock_logger() -> MagicMock:
    """Mock logger."""
    return MagicMock(spec=logging.Logger)


@pytest.fixture
def processor(
    mock_notification_service: AsyncMock, mock_logger: MagicMock
) -> GrafanaAlertProcessor:
    """Create processor with mocked dependencies."""
    return GrafanaAlertProcessor(
        notification_service=mock_notification_service, logger=mock_logger
    )


class TestExtractSeverity:
    """Tests for extract_severity class method."""

    @pytest.mark.parametrize(
        "alert_labels,webhook_labels,expected",
        [
            # Alert label takes precedence
            ({"severity": "critical"}, {"severity": "warning"}, "critical"),
            ({"severity": "ERROR"}, {}, "error"),  # Case insensitivity
            # Webhook label used when alert has none
            ({}, {"severity": "warning"}, "warning"),
            ({"other": "value"}, {"severity": "info"}, "info"),
            # Default when both empty
            ({}, {}, "warning"),
            (None, None, "warning"),
        ],
        ids=[
            "alert-precedence",
            "case-insensitive",
            "webhook-fallback",
            "webhook-with-other-labels",
            "default-empty",
            "default-none",
        ],
    )
    def test_extract_severity_combinations(
        self,
        alert_labels: dict[str, str] | None,
        webhook_labels: dict[str, str] | None,
        expected: str,
    ) -> None:
        """Extracts severity from alert/webhook labels with correct precedence."""
        alert = GrafanaAlertItem(labels=alert_labels or {})
        webhook = GrafanaWebhook(commonLabels=webhook_labels or {})

        result = GrafanaAlertProcessor.extract_severity(alert, webhook)

        assert result == expected


class TestMapSeverity:
    """Tests for map_severity class method."""

    @pytest.mark.parametrize(
        "severity_str,alert_status,expected",
        [
            # Standard severity mapping
            ("critical", None, NotificationSeverity.HIGH),
            ("error", None, NotificationSeverity.HIGH),
            ("warning", None, NotificationSeverity.MEDIUM),
            ("info", None, NotificationSeverity.LOW),
            # Unknown severity defaults to MEDIUM
            ("unknown", None, NotificationSeverity.MEDIUM),
            ("", None, NotificationSeverity.MEDIUM),
            # Resolved statuses override to LOW
            ("critical", "ok", NotificationSeverity.LOW),
            ("critical", "resolved", NotificationSeverity.LOW),
            ("error", "OK", NotificationSeverity.LOW),  # Case insensitivity
            ("error", "RESOLVED", NotificationSeverity.LOW),
            # Non-resolved statuses preserve severity
            ("critical", "firing", NotificationSeverity.HIGH),
            ("warning", "pending", NotificationSeverity.MEDIUM),
        ],
        ids=[
            "critical-no-status",
            "error-no-status",
            "warning-no-status",
            "info-no-status",
            "unknown-default",
            "empty-default",
            "critical-ok-resolved",
            "critical-resolved",
            "error-OK-case",
            "error-RESOLVED-case",
            "critical-firing",
            "warning-pending",
        ],
    )
    def test_map_severity_combinations(
        self,
        severity_str: str,
        alert_status: str | None,
        expected: NotificationSeverity,
    ) -> None:
        """Maps string severity to enum with status consideration."""
        result = GrafanaAlertProcessor.map_severity(severity_str, alert_status)
        assert result == expected


class TestExtractTitle:
    """Tests for extract_title class method."""

    @pytest.mark.parametrize(
        "labels,annotations,expected",
        [
            # alertname in labels takes precedence
            ({"alertname": "HighCPU"}, {"title": "CPU Alert"}, "HighCPU"),
            ({"alertname": "DiskFull"}, {}, "DiskFull"),
            # Title annotation as fallback
            ({}, {"title": "Memory Warning"}, "Memory Warning"),
            ({"other": "label"}, {"title": "Network Issue"}, "Network Issue"),
            # Default when nothing found
            ({}, {}, "Grafana Alert"),
            (None, None, "Grafana Alert"),
        ],
        ids=[
            "alertname-precedence",
            "alertname-only",
            "title-annotation",
            "title-with-other-labels",
            "default-empty",
            "default-none",
        ],
    )
    def test_extract_title_combinations(
        self,
        labels: dict[str, str] | None,
        annotations: dict[str, str] | None,
        expected: str,
    ) -> None:
        """Extracts title from labels/annotations with correct precedence."""
        alert = GrafanaAlertItem(
            labels=labels or {}, annotations=annotations or {}
        )

        result = GrafanaAlertProcessor.extract_title(alert)

        assert result == expected


class TestBuildMessage:
    """Tests for build_message class method."""

    @pytest.mark.parametrize(
        "annotations,expected",
        [
            # Summary and description combined
            (
                {"summary": "High CPU usage", "description": "CPU at 95%"},
                "High CPU usage\n\nCPU at 95%",
            ),
            # Summary only
            ({"summary": "Disk space low"}, "Disk space low"),
            # Description only
            ({"description": "Memory threshold exceeded"}, "Memory threshold exceeded"),
            # Empty annotations
            ({}, "Alert triggered"),
            (None, "Alert triggered"),
            # Other annotations ignored
            ({"other": "value"}, "Alert triggered"),
        ],
        ids=[
            "summary-and-description",
            "summary-only",
            "description-only",
            "empty-default",
            "none-default",
            "other-annotations-ignored",
        ],
    )
    def test_build_message_combinations(
        self,
        annotations: dict[str, str] | None,
        expected: str,
    ) -> None:
        """Builds message from annotations with correct formatting."""
        alert = GrafanaAlertItem(annotations=annotations or {})

        result = GrafanaAlertProcessor.build_message(alert)

        assert result == expected


class TestBuildMetadata:
    """Tests for build_metadata class method."""

    def test_includes_grafana_status_from_alert(self) -> None:
        """Metadata includes status from alert when available."""
        alert = GrafanaAlertItem(status="firing", labels={"env": "prod"})
        webhook = GrafanaWebhook(status="alerting")

        result = GrafanaAlertProcessor.build_metadata(alert, webhook, "critical")

        assert result["grafana_status"] == "firing"
        assert result["severity"] == "critical"

    def test_falls_back_to_webhook_status(self) -> None:
        """Metadata uses webhook status when alert status is None."""
        alert = GrafanaAlertItem(status=None)
        webhook = GrafanaWebhook(status="resolved")

        result = GrafanaAlertProcessor.build_metadata(alert, webhook, "info")

        assert result["grafana_status"] == "resolved"

    def test_merges_labels_with_alert_precedence(self) -> None:
        """Alert labels override webhook commonLabels."""
        alert = GrafanaAlertItem(labels={"env": "staging", "team": "platform"})
        webhook = GrafanaWebhook(commonLabels={"env": "prod", "region": "us-east"})

        result = GrafanaAlertProcessor.build_metadata(alert, webhook, "warning")

        assert result["env"] == "staging"  # Alert overrides webhook
        assert result["team"] == "platform"  # Alert-only
        assert result["region"] == "us-east"  # Webhook-only


class TestProcessSingleAlert:
    """Tests for process_single_alert method."""

    async def test_successful_alert_processing(
        self,
        processor: GrafanaAlertProcessor,
        mock_notification_service: AsyncMock,
    ) -> None:
        """Successfully processes alert and creates notification."""
        alert = GrafanaAlertItem(
            status="firing",
            labels={"alertname": "TestAlert", "severity": "critical"},
            annotations={"summary": "Test summary"},
        )
        webhook = GrafanaWebhook(status="alerting")

        success, error = await processor.process_single_alert(
            alert, webhook, "corr-123"
        )

        assert success is True
        assert error is None
        mock_notification_service.create_system_notification.assert_called_once()
        call_kwargs = mock_notification_service.create_system_notification.call_args.kwargs
        assert call_kwargs["title"] == "TestAlert"
        assert call_kwargs["message"] == "Test summary"
        assert call_kwargs["severity"] == NotificationSeverity.HIGH
        assert "grafana" in call_kwargs["tags"]

    async def test_handles_notification_service_error(
        self,
        processor: GrafanaAlertProcessor,
        mock_notification_service: AsyncMock,
        mock_logger: MagicMock,
    ) -> None:
        """Returns error tuple when notification service fails."""
        mock_notification_service.create_system_notification.side_effect = Exception(
            "DB connection failed"
        )
        alert = GrafanaAlertItem(labels={"alertname": "FailAlert"})
        webhook = GrafanaWebhook()

        success, error = await processor.process_single_alert(
            alert, webhook, "corr-456"
        )

        assert success is False
        assert error is not None
        assert "Failed to process Grafana alert" in error
        mock_logger.error.assert_called_once()


class TestProcessWebhook:
    """Tests for process_webhook method."""

    async def test_processes_all_alerts_in_webhook(
        self,
        processor: GrafanaAlertProcessor,
        mock_notification_service: AsyncMock,
    ) -> None:
        """Processes all alerts and returns correct count."""
        webhook = GrafanaWebhook(
            status="alerting",
            alerts=[
                GrafanaAlertItem(labels={"alertname": "Alert1"}),
                GrafanaAlertItem(labels={"alertname": "Alert2"}),
                GrafanaAlertItem(labels={"alertname": "Alert3"}),
            ],
        )

        processed, errors = await processor.process_webhook(webhook, "corr-789")

        assert processed == 3
        assert errors == []
        assert mock_notification_service.create_system_notification.call_count == 3

    async def test_handles_empty_alerts_list(
        self,
        processor: GrafanaAlertProcessor,
        mock_notification_service: AsyncMock,
    ) -> None:
        """Handles webhook with no alerts gracefully."""
        webhook = GrafanaWebhook(status="resolved", alerts=[])

        processed, errors = await processor.process_webhook(webhook, "corr-empty")

        assert processed == 0
        assert errors == []
        mock_notification_service.create_system_notification.assert_not_called()

    async def test_continues_on_individual_alert_failure(
        self,
        processor: GrafanaAlertProcessor,
        mock_notification_service: AsyncMock,
    ) -> None:
        """Processes remaining alerts when one fails."""
        call_count = 0

        async def side_effect(*args: Any, **kwargs: Any) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Second alert failed")

        mock_notification_service.create_system_notification.side_effect = side_effect

        webhook = GrafanaWebhook(
            alerts=[
                GrafanaAlertItem(labels={"alertname": "Alert1"}),
                GrafanaAlertItem(labels={"alertname": "Alert2"}),
                GrafanaAlertItem(labels={"alertname": "Alert3"}),
            ]
        )

        processed, errors = await processor.process_webhook(webhook, "corr-partial")

        assert processed == 2  # 1 and 3 succeeded
        assert len(errors) == 1
        assert "Second alert failed" in errors[0]

    async def test_logs_webhook_processing_info(
        self,
        processor: GrafanaAlertProcessor,
        mock_logger: MagicMock,
    ) -> None:
        """Logs processing start and completion."""
        webhook = GrafanaWebhook(
            status="firing",
            alerts=[GrafanaAlertItem(labels={"alertname": "LogTest"})],
        )

        await processor.process_webhook(webhook, "corr-log")

        # Should have at least 2 info logs: start and completion
        assert mock_logger.info.call_count >= 2


class TestClassConstants:
    """Tests for class-level constants."""

    def test_severity_mapping_completeness(self) -> None:
        """SEVERITY_MAPPING covers expected severity strings."""
        mapping = GrafanaAlertProcessor.SEVERITY_MAPPING
        assert "critical" in mapping
        assert "error" in mapping
        assert "warning" in mapping
        assert "info" in mapping

    def test_resolved_statuses(self) -> None:
        """RESOLVED_STATUSES contains expected values."""
        statuses = GrafanaAlertProcessor.RESOLVED_STATUSES
        assert "ok" in statuses
        assert "resolved" in statuses

    def test_default_values(self) -> None:
        """Default constants have sensible values."""
        assert GrafanaAlertProcessor.DEFAULT_SEVERITY == "warning"
        assert GrafanaAlertProcessor.DEFAULT_TITLE == "Grafana Alert"
        assert GrafanaAlertProcessor.DEFAULT_MESSAGE == "Alert triggered"
