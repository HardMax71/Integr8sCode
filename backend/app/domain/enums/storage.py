"""Storage and execution error enums."""

from app.core.utils import StringEnum


class ExecutionErrorType(StringEnum):
    """Types of execution errors."""
    SYSTEM_ERROR = "system_error"
    TIMEOUT = "timeout"
    RESOURCE_LIMIT = "resource_limit"
    SCRIPT_ERROR = "script_error"
    PERMISSION_DENIED = "permission_denied"


class StorageType(StringEnum):
    """Types of storage backends."""
    DATABASE = "database"
    S3 = "s3"
    FILESYSTEM = "filesystem"
    REDIS = "redis"
