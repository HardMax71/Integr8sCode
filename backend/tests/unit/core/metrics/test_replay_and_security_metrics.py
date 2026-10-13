from unittest.mock import MagicMock

import pytest

from app.core.metrics import SecurityMetrics
from app.settings import Settings

pytestmark = pytest.mark.unit


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
