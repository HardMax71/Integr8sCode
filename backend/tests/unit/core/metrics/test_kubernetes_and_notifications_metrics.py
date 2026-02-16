import pytest
from app.core.metrics import KubernetesMetrics, NotificationMetrics
from app.settings import Settings

pytestmark = pytest.mark.unit


def test_kubernetes_metrics_methods(test_settings: Settings) -> None:
    """Test with no-op metrics."""
    m = KubernetesMetrics(test_settings)
    m.record_pod_creation_failure("quota")
    m.record_pod_created("success", "python")
    m.record_pod_creation_duration(0.4, "python")
    m.update_active_pod_creations(2)
    m.increment_active_pod_creations()
    m.decrement_active_pod_creations()
    m.record_config_map_created("ok")
    m.record_k8s_pod_created("success", "python")
    m.record_k8s_pod_creation_duration(0.3, "python")
    m.record_k8s_config_map_created("ok")
    m.increment_pod_monitor_watch_reconnects()
    m.record_pod_monitor_event_processing_duration(0.2, "ADDED")
    m.record_pod_monitor_event_published("PodRunning", "Running")
    m.record_pod_monitor_reconciliation_run("ok")
    m.record_pod_monitor_watch_error("EOF")
    m.update_pod_monitor_pods_watched(3)
    m.record_pod_phase_transition("Pending", "Running", "pod1")
    m.record_pod_lifetime(12.0, "Succeeded", "python")
    m.update_pods_by_phase("Running", 2)


def test_notification_metrics_methods(test_settings: Settings) -> None:
    """Test with no-op metrics."""
    m = NotificationMetrics(test_settings)
    m.record_notification_sent("welcome", channel="email", severity="high")
    m.record_notification_failed("welcome", "smtp_error", channel="email")
    m.record_notification_delivery_time(0.5, "welcome", channel="email")
    m.record_notification_status_change("n1", "pending", "queued")
    m.record_notification_read("welcome")
    m.decrement_unread_count("u1")
    m.record_notification_throttled("welcome", "u1")
    m.record_throttle_window_hit("u1")
    m.record_notification_retry("welcome", 1, False)
    m.record_notification_retry("welcome", 2, True)
    m.record_webhook_delivery(0.3, 200, "/hooks/*")
    m.record_slack_delivery(0.4, "#general", False, error_type="rate_limited")
    m.update_active_subscriptions("u1", 3)
    m.update_active_subscriptions("u1", 1)
    m.record_subscription_change("u1", "welcome", "subscribe")
    m.increment_pending_notifications()
    m.decrement_pending_notifications()
    m.increment_queued_notifications()
    m.decrement_queued_notifications()
