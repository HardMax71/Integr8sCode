import time
from collections.abc import Generator
from contextlib import contextmanager

from app.core.metrics.base import BaseMetrics


class SecurityMetrics(BaseMetrics):
    """Metrics for security events."""

    def _create_instruments(self) -> None:
        # Authentication metrics
        self.authentication_attempts = self._meter.create_counter(
            name="authentication.attempts.total", description="Total number of authentication attempts", unit="1"
        )

        self.authentication_failures = self._meter.create_counter(
            name="authentication.failures.total", description="Total number of failed authentications", unit="1"
        )

        self.authentication_duration = self._meter.create_histogram(
            name="authentication.duration", description="Time taken for authentication in seconds", unit="s"
        )

        self.active_sessions = self._meter.create_up_down_counter(
            name="authentication.sessions.active", description="Number of active user sessions", unit="1"
        )

        # Token metrics
        self.tokens_generated = self._meter.create_counter(
            name="tokens.generated.total", description="Total number of tokens generated", unit="1"
        )

        self.tokens_revoked = self._meter.create_counter(
            name="tokens.revoked.total", description="Total number of tokens revoked", unit="1"
        )

        self.token_validation_failures = self._meter.create_counter(
            name="token.validation.failures.total", description="Total number of token validation failures", unit="1"
        )

        self.token_expiry_time = self._meter.create_histogram(
            name="token.expiry.time", description="Token expiry time in seconds", unit="s"
        )

        # Authorization metrics
        self.authorization_checks = self._meter.create_counter(
            name="authorization.checks.total", description="Total number of authorization checks", unit="1"
        )

        self.authorization_denials = self._meter.create_counter(
            name="authorization.denials.total", description="Total number of authorization denials", unit="1"
        )

        # CSRF protection metrics
        self.csrf_tokens_generated = self._meter.create_counter(
            name="csrf.tokens.generated.total", description="Total number of CSRF tokens generated", unit="1"
        )

        self.csrf_validation_failures = self._meter.create_counter(
            name="csrf.validation.failures.total", description="Total number of CSRF validation failures", unit="1"
        )

        # Password metrics
        self.password_reset_requests = self._meter.create_counter(
            name="password.reset.requests.total", description="Total number of password reset requests", unit="1"
        )

        self.weak_password_attempts = self._meter.create_counter(
            name="weak.password.attempts.total", description="Total number of weak password attempts", unit="1"
        )

        # Brute force detection
        self.brute_force_attempts = self._meter.create_counter(
            name="brute.force.attempts.total", description="Total number of detected brute force attempts", unit="1"
        )

        self.accounts_locked = self._meter.create_counter(
            name="accounts.locked.total", description="Total number of accounts locked due to security", unit="1"
        )

    def record_authentication_attempt(self, method: str, success: bool, duration_seconds: float) -> None:
        attrs = {"method": method, "success": str(success)}
        self.authentication_attempts.add(1, attributes=attrs)
        if not success:
            self.authentication_failures.add(1, attributes={"method": method})
        self.authentication_duration.record(duration_seconds, attributes={"method": method})

    @contextmanager
    def track_authentication(self, method: str) -> Generator[None, None, None]:
        start = time.monotonic()
        success = False
        try:
            yield
            success = True
        finally:
            self.record_authentication_attempt(method, success, time.monotonic() - start)

    def increment_active_sessions(self) -> None:
        self.active_sessions.add(1)

    def decrement_active_sessions(self) -> None:
        self.active_sessions.add(-1)

    def record_token_generated(self, token_type: str, expiry_seconds: float) -> None:
        self.tokens_generated.add(1, attributes={"token_type": token_type})
        self.token_expiry_time.record(expiry_seconds, attributes={"token_type": token_type})

    def record_token_revoked(self, token_type: str, reason: str) -> None:
        self.tokens_revoked.add(1, attributes={"token_type": token_type, "reason": reason})

    def record_token_validation_failure(self, token_type: str, failure_reason: str) -> None:
        self.token_validation_failures.add(1, attributes={"token_type": token_type, "failure_reason": failure_reason})

    def record_authorization_check(
        self, resource: str, action: str, allowed: bool, user_role: str | None = None
    ) -> None:
        self.authorization_checks.add(
            1,
            attributes={
                "resource": resource,
                "action": action,
                "allowed": str(allowed),
                "user_role": user_role or "unknown",
            },
        )

        if not allowed:
            self.authorization_denials.add(
                1, attributes={"resource": resource, "action": action, "user_role": user_role or "unknown"}
            )

    def record_csrf_token_generated(self) -> None:
        self.csrf_tokens_generated.add(1)

    def record_csrf_validation_failure(self, reason: str) -> None:
        self.csrf_validation_failures.add(1, attributes={"reason": reason})

    def record_password_reset_request(self, method: str = "admin") -> None:
        self.password_reset_requests.add(1, attributes={"method": method})

    def record_weak_password_attempt(self, weakness_type: str) -> None:
        self.weak_password_attempts.add(1, attributes={"weakness_type": weakness_type})

    def record_brute_force_attempt(
        self, ip_address: str, target_user: str | None = None, action_taken: str = "logged"
    ) -> None:
        self.brute_force_attempts.add(
            1,
            attributes={
                "ip_address": ip_address,
                "target_user": target_user or "multiple",
                "action_taken": action_taken,
            },
        )

    def record_account_locked(self, reason: str, duration_seconds: float | None = None) -> None:
        self.accounts_locked.add(
            1,
            attributes={
                "reason": reason,
                "duration": str(duration_seconds) if duration_seconds else "permanent",
            },
        )
