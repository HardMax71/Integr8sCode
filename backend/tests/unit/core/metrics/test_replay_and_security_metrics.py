
import pytest

from app.core.metrics.replay import ReplayMetrics
from app.core.metrics.security import SecurityMetrics


pytestmark = pytest.mark.unit


def test_replay_metrics_methods() -> None:
    """Test ReplayMetrics methods with no-op metrics."""
    # Create ReplayMetrics instance - will use NoOpMeterProvider automatically
    m = ReplayMetrics()
    m.record_session_created("by_id", "kafka")
    m.update_active_replays(2); m.increment_active_replays(); m.decrement_active_replays()
    m.record_events_replayed("by_id", "etype", "success", 3)
    m.record_event_replayed("by_id", "etype", "failed")
    m.record_replay_duration(2.0, "by_id", total_events=4)
    m.record_event_processing_time(0.1, "etype")
    m.record_replay_error("timeout", "by_id")
    m.record_status_change("s1", "running", "completed")
    m.update_sessions_by_status("running", -1)
    m.record_replay_by_target("kafka", True); m.record_replay_by_target("kafka", False)
    m.record_speed_multiplier(2.0, "by_id")
    m.record_delay_applied(0.05)
    m.record_batch_size(10, "by_id")
    m.record_events_filtered("type", 5)
    m.record_filter_effectiveness(5, 10, "type")
    m.record_replay_memory_usage(123.0, "s1")
    m.update_replay_queue_size("s1", 10); m.update_replay_queue_size("s1", 4)


def test_security_metrics_methods() -> None:
    """Test SecurityMetrics methods with no-op metrics."""
    # Create SecurityMetrics instance - will use NoOpMeterProvider automatically
    m = SecurityMetrics()
    m.record_security_event("scan_started", severity="high", source="scanner")
    m.record_security_violation("csrf", user_id="u1", ip_address="127.0.0.1")
    m.record_authentication_attempt("password", False, user_id="u1", duration_seconds=0.2)
    m.update_active_sessions(2); m.increment_active_sessions(); m.decrement_active_sessions()
    m.record_token_generated("access", 3600); m.record_token_refreshed("access"); m.record_token_revoked("access", "logout")
    m.record_token_validation_failure("access", "expired")
    m.record_authorization_check("/admin", "GET", False, user_role="user")
    m.record_permission_check("write", True, user_id="u1")
    m.record_csrf_token_generated(); m.record_csrf_validation_failure("missing")
    m.record_network_policy_violation("np1", "pod1", violation_type="egress")
    m.record_privilege_escalation_attempt("u1", "admin", True)
    m.record_rate_limit_hit("/api"); m.record_rate_limit_violation("/api", limit=100)
    m.record_api_key_created("kid"); m.record_api_key_revoked("kid", "compromised"); m.record_api_key_usage("kid", "/api")
    m.record_audit_event("config_change", "u1", resource="system"); m.record_password_change("u1", True)
    m.record_password_reset_request("u1", method="email")
    m.record_weak_password_attempt("u1", "common_password")
    m.record_brute_force_attempt("1.2.3.4", target_user="u1", action_taken="blocked")
    m.record_account_locked("u1", "brute_force", duration_seconds=600)

