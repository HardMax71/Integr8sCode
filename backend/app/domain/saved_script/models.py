from typing import TypedDict


class SavedScriptChanges(TypedDict, total=False):
    """Fields an update sets; a missing key keeps the stored value and None clears the description."""

    name: str
    script: str
    lang: str
    lang_version: str
    description: str | None
