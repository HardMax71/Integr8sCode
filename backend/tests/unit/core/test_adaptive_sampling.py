import time
from unittest.mock import patch

import pytest

from app.core.adaptive_sampling import AdaptiveSampler, create_adaptive_sampler


def test_is_error_variants() -> None:
    # Mock the thread start to avoid background thread delays in tests
    with patch.object(AdaptiveSampler, '_adjustment_loop', return_value=None):
        s = AdaptiveSampler(base_rate=0.5, adjustment_interval=1)
        # Plain error flag
        assert s._is_error({"error": True}) is True
        # HTTP status >= 500
        assert s._is_error({"http.status_code": 500}) is True
        assert s._is_error({"http.status_code": "503"}) is True
        # Exception present
        assert s._is_error({"exception.type": "ValueError"}) is True
        # Not error
        assert s._is_error({"http.status_code": 200}) is False
        s._running = False  # Ensure cleanup


def test_should_sample_respects_rate() -> None:
    with patch('threading.Thread'):  # Mock thread to avoid background delays
        s = AdaptiveSampler(base_rate=1.0, adjustment_interval=1)
        # With current_rate=1.0, all trace_ids sample
        res = s.should_sample(None, trace_id=123, name="op")
        assert res.decision.value == 2  # RECORD_AND_SAMPLE
        # With rate ~0, most should drop; we choose large id to exceed threshold
        s._current_rate = 0.0
        res2 = s.should_sample(None, trace_id=(1 << 64) - 1, name="op")
        assert res2.decision.value in (0, 1)  # DROP or RECORD_ONLY depending impl
        s._running = False


def test_adjust_sampling_rate_error_and_traffic() -> None:
    with patch('threading.Thread'):  # Mock thread to avoid background delays
        s = AdaptiveSampler(base_rate=0.1, adjustment_interval=1)
        now = time.time()
        # Simulate 100 requests in window with 10 errors (> threshold 5%)
        s._request_window.clear()
        s._error_window.clear()
        for _ in range(100):
            s._request_window.append(now)
        for _ in range(10):
            s._error_window.append(now)
        old = s._current_rate
        s._adjust_sampling_rate()
        assert s._current_rate >= old
        # Simulate high traffic and low errors -> decrease toward min_rate
        s._request_window.clear()
        s._error_window.clear()
        for _ in range(2000):
            s._request_window.append(now)
        old2 = s._current_rate
        s._adjust_sampling_rate()
        assert s._current_rate <= old2
        s._running = False


def test_get_description_and_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    with patch('threading.Thread'):  # Mock thread to avoid background delays
        s = AdaptiveSampler(base_rate=0.2, adjustment_interval=1)
        desc = s.get_description()
        assert "AdaptiveSampler(" in desc
        s._running = False

        class S:
            TRACING_SAMPLING_RATE = 0.2

        monkeypatch.setenv("TRACING_SAMPLING_RATE", "0.2")
        # create_adaptive_sampler pulls settings via get_settings; just ensure it constructs
        sampler = create_adaptive_sampler(S())
        sampler._running = False

