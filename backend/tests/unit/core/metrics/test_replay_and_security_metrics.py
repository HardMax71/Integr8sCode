from unittest.mock import MagicMock

import pytest

from app.core.metrics import ReplayMetrics, SecurityMetrics
from app.settings import Settings

pytestmark = pytest.mark.unit


def test_replay_metrics_methods(test_settings: Settings) -> None:
    """Test ReplayMetrics methods with no-op metrics."""
    m = ReplayMetrics(test_settings)
    m.record_session_created("by_id", "kafka")
    m.increment_active_replays()
    m.decrement_active_replays()
    m.record_event_replayed("by_id", "etype", True)
    m.record_event_replayed("by_id", "etype", False)
    m.record_replay_duration(2.0, "by_id", total_events=4)
    m.record_event_processing_time(0.1, "etype")
    m.record_status_change("s1", "running", "completed")
    m.update_sessions_by_status("running", -1)
    m.record_replay_by_target("kafka", True)
    m.record_replay_by_target("kafka", False)
    m.record_speed_multiplier(2.0, "by_id")
    m.record_delay_applied(0.05)
    m.record_batch_size(10, "by_id")
    m.update_replay_queue_size("s1", 10)
    m.update_replay_queue_size("s1", 4)


def test_security_metrics_methods(test_settings: Settings) -> None:
    """Test SecurityMetrics methods with no-op metrics."""
    m = SecurityMetrics(test_settings)
    with m.track_authentication("password"):
        pass
    m.record_token_validation_failure("expired")
    m.record_authorization_check("/admin", "GET", False, user_role="user")
    m.record_csrf_validation_failure("missing")
    m.record_password_reset_request(method="admin")
    m.record_weak_password_attempt("common_password")
    m.record_brute_force_attempt()
    m.record_account_locked("brute_force")


def test_track_authentication_counts_a_raised_login_as_failure(test_settings: Settings) -> None:
    m = SecurityMetrics(test_settings)
    m.authentication_attempts = MagicMock()
    m.authentication_failures = MagicMock()
    m.authentication_duration = MagicMock()

    with pytest.raises(ValueError), m.track_authentication("login"):
        raise ValueError("bad password")

    m.authentication_attempts.add.assert_called_once_with(1, attributes={"method": "login", "success": "False"})
    m.authentication_failures.add.assert_called_once_with(1, attributes={"method": "login"})
    m.authentication_duration.record.assert_called_once()
