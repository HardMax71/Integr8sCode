from app.core.utils import StringEnum


class LoginMethod(StringEnum):
    """User login methods."""

    PASSWORD = "password"
    OAUTH = "oauth"
    SSO = "sso"
    API_KEY = "api_key"


class SettingsType(StringEnum):
    """Types of user settings."""

    PREFERENCES = "preferences"
    NOTIFICATION = "notification"
    EDITOR = "editor"
    SECURITY = "security"
    DISPLAY = "display"
