from app.core.metrics.base import BaseMetrics


class SecurityMetrics(BaseMetrics):
    """Metrics for security events."""

    def _create_instruments(self) -> None:
        # Core security event metrics
        self.security_events = self._meter.create_counter(
            name="security.events.total", description="Total number of security events by type", unit="1"
        )

        self.security_violations = self._meter.create_counter(
            name="security.violations.total", description="Total number of security violations", unit="1"
        )

        self.security_alerts = self._meter.create_counter(
            name="security.alerts.total", description="Total number of security alerts raised", unit="1"
        )

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

        self.tokens_refreshed = self._meter.create_counter(
            name="tokens.refreshed.total", description="Total number of tokens refreshed", unit="1"
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

        self.permission_checks = self._meter.create_counter(
            name="permission.checks.total", description="Total number of permission checks", unit="1"
        )

        # CSRF protection metrics
        self.csrf_tokens_generated = self._meter.create_counter(
            name="csrf.tokens.generated.total", description="Total number of CSRF tokens generated", unit="1"
        )

        self.csrf_validation_failures = self._meter.create_counter(
            name="csrf.validation.failures.total", description="Total number of CSRF validation failures", unit="1"
        )

        # Network security metrics
        self.network_policy_violations = self._meter.create_counter(
            name="network.policy.violations.total", description="Total number of network policy violations", unit="1"
        )

        self.network_policy_created = self._meter.create_counter(
            name="network.policies.created.total", description="Total number of network policies created", unit="1"
        )

        # Privilege escalation metrics
        self.privilege_escalation_attempts = self._meter.create_counter(
            name="privilege.escalation.attempts.total",
            description="Total number of privilege escalation attempts",
            unit="1",
        )

        self.privilege_escalation_blocked = self._meter.create_counter(
            name="privilege.escalation.blocked.total",
            description="Total number of blocked privilege escalation attempts",
            unit="1",
        )

        # Rate limiting metrics
        self.rate_limit_hits = self._meter.create_counter(
            name="rate.limit.hits.total", description="Total number of rate limit hits", unit="1"
        )

        self.rate_limit_violations = self._meter.create_counter(
            name="rate.limit.violations.total", description="Total number of rate limit violations", unit="1"
        )

        # API key metrics
        self.api_keys_created = self._meter.create_counter(
            name="api.keys.created.total", description="Total number of API keys created", unit="1"
        )

        self.api_keys_revoked = self._meter.create_counter(
            name="api.keys.revoked.total", description="Total number of API keys revoked", unit="1"
        )

        self.api_key_usage = self._meter.create_counter(
            name="api.key.usage.total", description="Total API key usage", unit="1"
        )

        # Audit log metrics
        self.audit_events_logged = self._meter.create_counter(
            name="audit.events.logged.total", description="Total number of audit events logged", unit="1"
        )

        # Password metrics
        self.password_changes = self._meter.create_counter(
            name="password.changes.total", description="Total number of password changes", unit="1"
        )

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

    def record_security_event(self, event_type: str, severity: str = "info", source: str = "system") -> None:
        self.security_events.add(1, attributes={"event_type": event_type, "severity": severity, "source": source})

        if severity in ["critical", "high"]:
            self.security_alerts.add(1, attributes={"event_type": event_type, "severity": severity})

    def record_security_violation(
        self, violation_type: str, user_id: str | None = None, ip_address: str | None = None
    ) -> None:
        self.security_violations.add(
            1,
            attributes={
                "violation_type": violation_type,
                "user_id": user_id or "anonymous",
                "ip_address": ip_address or "unknown",
            },
        )

    def record_authentication_attempt(
        self, method: str, success: bool, user_id: str | None = None, duration_seconds: float | None = None
    ) -> None:
        self.authentication_attempts.add(
            1, attributes={"method": method, "success": str(success), "user_id": user_id or "unknown"}
        )

        if not success:
            self.authentication_failures.add(1, attributes={"method": method, "user_id": user_id or "unknown"})

        if duration_seconds is not None:
            self.authentication_duration.record(duration_seconds, attributes={"method": method})

    def update_active_sessions(self, count: int) -> None:
        # Track the delta for gauge-like behavior
        key = "_active_sessions"
        current_val = getattr(self, key, 0)
        delta = count - current_val
        if delta != 0:
            self.active_sessions.add(delta)
        setattr(self, key, count)

    def increment_active_sessions(self) -> None:
        self.active_sessions.add(1)

    def decrement_active_sessions(self) -> None:
        self.active_sessions.add(-1)

    def record_token_generated(self, token_type: str, expiry_seconds: float) -> None:
        self.tokens_generated.add(1, attributes={"token_type": token_type})

        self.token_expiry_time.record(expiry_seconds, attributes={"token_type": token_type})

    def record_token_refreshed(self, token_type: str) -> None:
        self.tokens_refreshed.add(1, attributes={"token_type": token_type})

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

    def record_permission_check(self, permission: str, granted: bool, user_id: str | None = None) -> None:
        self.permission_checks.add(
            1, attributes={"permission": permission, "granted": str(granted), "user_id": user_id or "unknown"}
        )

    def record_csrf_token_generated(self) -> None:
        self.csrf_tokens_generated.add(1)

    def record_csrf_validation_failure(self, reason: str) -> None:
        self.csrf_validation_failures.add(1, attributes={"reason": reason})

    def record_network_policy_violation(
        self, policy_name: str, pod_name: str | None = None, violation_type: str = "ingress"
    ) -> None:
        self.network_policy_violations.add(
            1,
            attributes={
                "policy_name": policy_name,
                "pod_name": pod_name or "unknown",
                "violation_type": violation_type,
            },
        )

    def record_privilege_escalation_attempt(self, user_id: str, target_privilege: str, blocked: bool) -> None:
        self.privilege_escalation_attempts.add(
            1, attributes={"user_id": user_id, "target_privilege": target_privilege, "blocked": str(blocked)}
        )

        if blocked:
            self.privilege_escalation_blocked.add(
                1, attributes={"user_id": user_id, "target_privilege": target_privilege}
            )

    def record_rate_limit_hit(self, endpoint: str, user_id: str | None = None) -> None:
        self.rate_limit_hits.add(1, attributes={"endpoint": endpoint, "user_id": user_id or "anonymous"})

    def record_rate_limit_violation(self, endpoint: str, user_id: str | None = None, limit: int | None = None) -> None:
        self.rate_limit_violations.add(
            1,
            attributes={
                "endpoint": endpoint,
                "user_id": user_id or "anonymous",
                "limit": str(limit) if limit else "unknown",
            },
        )

    def record_api_key_created(self, key_id: str, scopes: str | None = None) -> None:
        self.api_keys_created.add(1, attributes={"key_id": key_id, "scopes": scopes or "default"})

    def record_api_key_revoked(self, key_id: str, reason: str) -> None:
        self.api_keys_revoked.add(1, attributes={"key_id": key_id, "reason": reason})

    def record_api_key_usage(self, key_id: str, endpoint: str) -> None:
        self.api_key_usage.add(1, attributes={"key_id": key_id, "endpoint": endpoint})

    def record_audit_event(self, event_type: str, user_id: str, resource: str | None = None) -> None:
        self.audit_events_logged.add(
            1, attributes={"event_type": event_type, "user_id": user_id, "resource": resource or "system"}
        )

    def record_password_change(self, user_id: str, forced: bool = False) -> None:
        self.password_changes.add(1, attributes={"user_id": user_id, "forced": str(forced)})

    def record_password_reset_request(self, user_id: str, method: str = "email") -> None:
        self.password_reset_requests.add(1, attributes={"user_id": user_id, "method": method})

    def record_weak_password_attempt(self, user_id: str, weakness_type: str) -> None:
        self.weak_password_attempts.add(1, attributes={"user_id": user_id, "weakness_type": weakness_type})

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

    def record_account_locked(self, user_id: str, reason: str, duration_seconds: float | None = None) -> None:
        self.accounts_locked.add(
            1,
            attributes={
                "user_id": user_id,
                "reason": reason,
                "duration": str(duration_seconds) if duration_seconds else "permanent",
            },
        )
