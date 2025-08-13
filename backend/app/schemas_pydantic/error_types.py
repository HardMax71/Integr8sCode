"""Error type classification for execution results."""
from enum import StrEnum


class ErrorType(StrEnum):
    """Classification of error types in execution platform."""
    SCRIPT_ERROR = "script_error"  # User code had errors
    SYSTEM_ERROR = "system_error"  # Infrastructure/platform issues
    SUCCESS = "success"  # No errors
