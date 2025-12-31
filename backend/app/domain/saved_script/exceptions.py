from app.domain.exceptions import NotFoundError


class SavedScriptNotFoundError(NotFoundError):
    """Raised when a saved script is not found."""

    def __init__(self, script_id: str) -> None:
        super().__init__("Script", script_id)
