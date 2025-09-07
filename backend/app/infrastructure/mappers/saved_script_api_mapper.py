from __future__ import annotations

from typing import List

from app.domain.saved_script.models import (
    DomainSavedScript,
    DomainSavedScriptCreate,
    DomainSavedScriptUpdate,
)
from app.schemas_pydantic.saved_script import (
    SavedScriptCreateRequest,
    SavedScriptResponse,
)


class SavedScriptApiMapper:
    @staticmethod
    def request_to_create(req: SavedScriptCreateRequest) -> DomainSavedScriptCreate:
        return DomainSavedScriptCreate(
            name=req.name,
            script=req.script,
            lang=req.lang,
            lang_version=req.lang_version,
            description=req.description,
        )

    @staticmethod
    def request_to_update(req: SavedScriptCreateRequest) -> DomainSavedScriptUpdate:
        return DomainSavedScriptUpdate(
            name=req.name,
            script=req.script,
            lang=req.lang,
            lang_version=req.lang_version,
            description=req.description,
        )

    @staticmethod
    def to_response(s: DomainSavedScript) -> SavedScriptResponse:
        return SavedScriptResponse(
            script_id=s.script_id,
            name=s.name,
            script=s.script,
            lang=s.lang,
            lang_version=s.lang_version,
            description=s.description,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )

    @staticmethod
    def list_to_response(items: List[DomainSavedScript]) -> List[SavedScriptResponse]:
        return [SavedScriptApiMapper.to_response(i) for i in items]

