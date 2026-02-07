import time
from unittest.mock import MagicMock

import pytest
from app.core.adaptive_sampling import AdaptiveSampler, create_adaptive_sampler
from app.settings import Settings


def test_is_error_variants() -> None:
    s = AdaptiveSampler(base_rate=0.5, adjustment_interval=1)
    assert s._is_error({"error": True}) is True
    assert s._is_error({"http.status_code": 500}) is True
    assert s._is_error({"http.status_code": "503"}) is True
    assert s._is_error({"exception.type": "ValueError"}) is True
    assert s._is_error({"http.status_code": 200}) is False


def test_should_sample_respects_rate() -> None:
    s = AdaptiveSampler(base_rate=1.0, adjustment_interval=1)
    # With current_rate=1.0, all trace_ids sample
    res = s.should_sample(None, trace_id=123, name="op")
    assert res.decision.value == 2  # RECORD_AND_SAMPLE
    # With rate ~0, most should drop; we choose large id to exceed threshold
    s._current_rate = 0.0
    res2 = s.should_sample(None, trace_id=(1 << 64) - 1, name="op")
    assert res2.decision.value in (0, 1)  # DROP or RECORD_ONLY depending impl


def test_adjust_sampling_rate_error_and_traffic() -> None:
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


def test_get_description_and_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    s = AdaptiveSampler(base_rate=0.2, adjustment_interval=1)
    desc = s.get_description()
    assert "AdaptiveSampler(" in desc

    mock_settings = MagicMock(spec=Settings)
    mock_settings.TRACING_SAMPLING_RATE = 0.2

    monkeypatch.setenv("TRACING_SAMPLING_RATE", "0.2")
    sampler = create_adaptive_sampler(mock_settings)
    assert sampler._current_rate == 0.2
