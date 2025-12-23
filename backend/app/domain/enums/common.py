from app.core.utils import StringEnum


class ErrorType(StringEnum):
    """Classification of error types in execution platform."""

    SCRIPT_ERROR = "script_error"  # User code had errors
    SYSTEM_ERROR = "system_error"  # Infrastructure/platform issues
    SUCCESS = "success"  # No errors


class Theme(StringEnum):
    """Available UI themes."""

    LIGHT = "light"
    DARK = "dark"
    AUTO = "auto"


class SortOrder(StringEnum):
    """Sort order for queries."""

    ASC = "asc"
    DESC = "desc"


class Environment(StringEnum):
    """Deployment environments."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"
