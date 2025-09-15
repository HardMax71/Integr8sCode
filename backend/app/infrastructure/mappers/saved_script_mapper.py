from dataclasses import asdict, fields
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.domain.saved_script import (
    DomainSavedScript,
    DomainSavedScriptCreate,
    DomainSavedScriptUpdate,
)


class SavedScriptMapper:
    """Mapper for Saved Script domain models to/from MongoDB docs."""

    @staticmethod
    def to_insert_document(create: DomainSavedScriptCreate, user_id: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        return {
            "script_id": str(uuid4()),
            "user_id": user_id,
            "name": create.name,
            "script": create.script,
            "lang": create.lang,
            "lang_version": create.lang_version,
            "description": create.description,
            "created_at": now,
            "updated_at": now,
        }

    @staticmethod
    def to_update_dict(update: DomainSavedScriptUpdate) -> dict[str, Any]:
        # Convert to dict and drop None fields; keep updated_at
        raw = asdict(update)
        return {k: v for k, v in raw.items() if v is not None}

    @staticmethod
    def from_mongo_document(doc: dict[str, Any]) -> DomainSavedScript:
        allowed = {f.name for f in fields(DomainSavedScript)}
        filtered = {k: v for k, v in doc.items() if k in allowed}
        # Coerce required fields to str where applicable for safety
        if "script_id" in filtered:
            filtered["script_id"] = str(filtered["script_id"])
        if "user_id" in filtered:
            filtered["user_id"] = str(filtered["user_id"])
        if "name" in filtered:
            filtered["name"] = str(filtered["name"])
        if "script" in filtered:
            filtered["script"] = str(filtered["script"])
        if "lang" in filtered:
            filtered["lang"] = str(filtered["lang"])
        if "lang_version" in filtered:
            filtered["lang_version"] = str(filtered["lang_version"])
        return DomainSavedScript(**filtered)  # dataclass defaults cover missing timestamps
