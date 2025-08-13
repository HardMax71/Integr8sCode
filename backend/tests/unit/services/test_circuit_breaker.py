from datetime import datetime, timedelta, timezone

from app.events.kafka.cb.manager import CircuitBreaker


class TestCircuitBreaker:
    def test_circuit_breaker_initialization(self) -> None:
        cb = CircuitBreaker()

        assert cb is not None
        assert cb.failure_threshold > 0
        assert cb.reset_timeout > 0
        assert cb.failures == 0
        assert cb.last_failure_time is None
        assert cb.is_open is False

    def test_circuit_breaker_custom_parameters(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=30)

        assert cb.failure_threshold == 3
        assert cb.reset_timeout == 30
        assert cb.failures == 0
        assert cb.is_open is False

    def test_circuit_breaker_should_allow_request_closed(self) -> None:
        cb = CircuitBreaker()

        assert cb.should_allow_request() is True

    def test_circuit_breaker_record_failure(self) -> None:
        cb = CircuitBreaker(failure_threshold=2)

        # First failure
        cb.record_failure()
        assert cb.failures == 1
        assert cb.last_failure_time is not None
        assert cb.is_open is False

        # Second failure should open circuit
        cb.record_failure()
        assert cb.failures == 2
        assert cb.is_open is True

    def test_circuit_breaker_record_success(self) -> None:
        cb = CircuitBreaker(failure_threshold=2)

        # Add failures
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True
        assert cb.failures == 2

        # Success should reset
        cb.record_success()
        assert cb.failures == 0
        assert cb.last_failure_time is None
        assert cb.is_open is False

    def test_circuit_breaker_should_allow_request_open(self) -> None:
        cb = CircuitBreaker(failure_threshold=1)

        # Open the circuit
        cb.record_failure()
        assert cb.is_open is True
        assert cb.should_allow_request() is False

    def test_circuit_breaker_timeout_recovery(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=1)  # 1 second timeout

        # Open the circuit
        cb.record_failure()
        assert cb.is_open is True
        assert cb.should_allow_request() is False

        # Manually set failure time to past for testing
        cb.last_failure_time = datetime.now(timezone.utc) - timedelta(seconds=2)

        # Should allow request after timeout
        assert cb.should_allow_request() is True
        assert cb.is_open is False
        assert cb.failures == 0

    def test_circuit_breaker_failure_threshold_boundary(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)

        # Add failures up to threshold - 1
        for i in range(2):
            cb.record_failure()
            assert cb.is_open is False

        assert cb.failures == 2

        # One more failure should open circuit
        cb.record_failure()
        assert cb.failures == 3
        assert cb.is_open is True

    def test_circuit_breaker_multiple_successes(self) -> None:
        cb = CircuitBreaker(failure_threshold=5)

        # Add some failures
        for i in range(3):
            cb.record_failure()

        assert cb.failures == 3
        assert cb.is_open is False

        # Success should reset all failures
        cb.record_success()
        assert cb.failures == 0

        # Multiple successes should keep it reset
        for i in range(3):
            cb.record_success()
            assert cb.failures == 0
            assert cb.is_open is False

    def test_circuit_breaker_failure_time_tracking(self) -> None:
        cb = CircuitBreaker()

        before_failure = datetime.now(timezone.utc)
        cb.record_failure()
        after_failure = datetime.now(timezone.utc)

        assert cb.last_failure_time is not None
        assert before_failure <= cb.last_failure_time <= after_failure

    def test_circuit_breaker_reset_timeout_boundary(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=5)

        # Open circuit
        cb.record_failure()
        original_failure_time = cb.last_failure_time
        assert cb.is_open is True

        # Just before timeout - should still be open
        cb.last_failure_time = datetime.now(timezone.utc) - timedelta(seconds=4)
        assert cb.should_allow_request() is False
        assert cb.is_open is True

        # Just after timeout - should allow requests
        cb.last_failure_time = datetime.now(timezone.utc) - timedelta(seconds=6)
        assert cb.should_allow_request() is True
        assert cb.is_open is False

    def test_circuit_breaker_state_consistency(self) -> None:
        cb = CircuitBreaker(failure_threshold=2)

        # Initial state
        assert cb.failures == 0
        assert cb.is_open is False
        assert cb.last_failure_time is None
        assert cb.should_allow_request() is True

        # After first failure
        cb.record_failure()
        assert cb.failures == 1
        assert cb.is_open is False
        assert cb.last_failure_time is not None
        assert cb.should_allow_request() is True

        # After threshold failures
        cb.record_failure()
        assert cb.failures == 2
        assert cb.is_open is True
        assert cb.should_allow_request() is False

        # After success
        cb.record_success()
        assert cb.failures == 0
        assert cb.is_open is False
        assert cb.last_failure_time is None
        assert cb.should_allow_request() is True

    def test_circuit_breaker_high_failure_threshold(self) -> None:
        cb = CircuitBreaker(failure_threshold=10)

        # Add many failures but still below threshold
        for i in range(9):
            cb.record_failure()
            assert cb.is_open is False

        assert cb.failures == 9

        # One more should open it
        cb.record_failure()
        assert cb.failures == 10
        assert cb.is_open is True

    def test_circuit_breaker_concurrent_simulation(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)

        # Simulate concurrent failures
        for i in range(3):
            cb.record_failure()

        assert cb.is_open is True

        # All requests should be blocked
        for i in range(5):
            assert cb.should_allow_request() is False

        # Success should reset for all
        cb.record_success()

        # All requests should be allowed again
        for i in range(5):
            assert cb.should_allow_request() is True

    def test_circuit_breaker_edge_case_zero_timeout(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=0)

        # Open circuit
        cb.record_failure()
        assert cb.is_open is True

        # With zero timeout, should immediately allow requests
        # (though this might not be practical in real usage)
        import time
        time.sleep(0.001)  # Small delay to ensure time difference

        # Manually set past time
        cb.last_failure_time = datetime.now(timezone.utc) - timedelta(milliseconds=1)

        assert cb.should_allow_request() is True

    def test_circuit_breaker_configuration_validation(self) -> None:
        # Test minimum values
        cb_min = CircuitBreaker(failure_threshold=1, reset_timeout=1)
        assert cb_min.failure_threshold == 1
        assert cb_min.reset_timeout == 1

        # Test larger values
        cb_large = CircuitBreaker(failure_threshold=100, reset_timeout=3600)
        assert cb_large.failure_threshold == 100
        assert cb_large.reset_timeout == 3600

    def test_circuit_breaker_repeated_operations(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=1)

        # Cycle 1: Open circuit
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True

        # Reset
        cb.record_success()
        assert cb.is_open is False

        # Cycle 2: Open again
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True

        # Reset again
        cb.record_success()
        assert cb.is_open is False
        assert cb.failures == 0

    def test_circuit_breaker_no_false_resets(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=10)  # Long timeout

        # Open circuit
        cb.record_failure()
        assert cb.is_open is True

        # Should not allow requests before timeout
        assert cb.should_allow_request() is False

        # Multiple checks should not change state
        for i in range(5):
            assert cb.should_allow_request() is False
            assert cb.is_open is True

    def test_circuit_breaker_attributes_exist(self) -> None:
        cb = CircuitBreaker()

        # Required attributes
        assert hasattr(cb, 'failure_threshold')
        assert hasattr(cb, 'reset_timeout')
        assert hasattr(cb, 'failures')
        assert hasattr(cb, 'last_failure_time')
        assert hasattr(cb, 'is_open')

        # Required methods
        assert hasattr(cb, 'record_failure')
        assert hasattr(cb, 'record_success')
        assert hasattr(cb, 'should_allow_request')
        assert callable(cb.record_failure)
        assert callable(cb.record_success)
        assert callable(cb.should_allow_request)
