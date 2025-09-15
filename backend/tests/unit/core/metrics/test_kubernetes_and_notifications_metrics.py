

import pytest

from app.core.metrics.kubernetes import KubernetesMetrics
from app.core.metrics.notifications import NotificationMetrics


pytestmark = pytest.mark.unit


def test_kubernetes_metrics_methods() -> None:
    """Test with no-op metrics."""
    
    m = KubernetesMetrics()
    m.record_pod_creation_failure("quota")
    m.record_pod_created("success", "python"); m.record_pod_creation_duration(0.4, "python")
    m.update_active_pod_creations(2); m.increment_active_pod_creations(); m.decrement_active_pod_creations()
    m.record_config_map_created("ok")
    m.record_k8s_pod_created("success", "python"); m.record_k8s_pod_creation_duration(0.3, "python")
    m.record_k8s_config_map_created("ok"); m.record_k8s_network_policy_created("ok")
    m.update_k8s_active_creations(1)
    m.increment_pod_monitor_watch_reconnects()
    m.record_pod_monitor_event_processing_duration(0.2, "ADDED")
    m.record_pod_monitor_event_published("PodRunning", "Running")
    m.record_pod_monitor_reconciliation_run("ok")
    m.record_pod_monitor_watch_error("EOF")
    m.update_pod_monitor_pods_watched(3)
    m.record_pod_phase_transition("Pending", "Running", "pod1")
    m.record_pod_lifetime(12.0, "Succeeded", "python")
    m.update_pods_by_phase("Running", 2)
    m.record_pod_resource_request("cpu", 500.0, "python")
    m.record_pod_resource_limit("memory", 256.0, "python")
    m.record_pods_per_node("node1", 7)


def test_notification_metrics_methods() -> None:
    """Test with no-op metrics."""
    
    m = NotificationMetrics()
    m.record_notification_sent("welcome", channel="email", severity="high")
    m.record_notification_failed("welcome", "smtp_error", channel="email")
    m.record_notification_delivery_time(0.5, "welcome", channel="email")
    m.record_notification_status_change("n1", "pending", "queued")
    m.record_notification_read("welcome", 2.0)
    m.record_notification_clicked("welcome")
    m.update_unread_count("u1", 5); m.update_unread_count("u1", 2)
    m.record_notification_throttled("welcome", "u1"); m.record_throttle_window_hit("u1")
    m.record_notification_retry("welcome", 1, False); m.record_notification_retry("welcome", 2, True)
    m.record_batch_processed(10, 1.2, notification_type="welcome")
    m.record_template_render(0.2, "tmpl", success=True); m.record_template_render(0.1, "tmpl", success=False)
    m.record_webhook_delivery(0.3, 200, "/hooks/*")
    m.record_slack_delivery(0.4, "#general", False, error_type="rate_limited")
    m.update_active_subscriptions("u1", 3); m.update_active_subscriptions("u1", 1)
    m.record_subscription_change("u1", "welcome", "subscribe")
    m.increment_pending_notifications(); m.decrement_pending_notifications()
    m.increment_queued_notifications(); m.decrement_queued_notifications()
