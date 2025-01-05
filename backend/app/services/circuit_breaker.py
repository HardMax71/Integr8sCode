from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.logging import logger

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, reset_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failures = 0
        self.last_failure_time: Optional[datetime] = None
        self.is_open = False

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = datetime.utcnow()
        if self.failures >= self.failure_threshold:
            self.is_open = True
            logger.error(f"Circuit breaker opened after {self.failures} failures")

    def record_success(self):
        self.failures = 0
        self.last_failure_time = None
        self.is_open = False

    def should_allow_request(self) -> bool:
        if not self.is_open:
            return True

        if self.last_failure_time and (
            datetime.now(timezone.utc) - self.last_failure_time
        ) > timedelta(seconds=self.reset_timeout):
            self.is_open = False
            self.failures = 0
            return True

        return False