"""Immutable rule pack manifests and their honest coverage."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from afterlap_contracts import ErrorCode, RuleManifest
from afterlap_contracts.requests import RulesetResponse

from ..db import LifecycleError
from ..db.models import RuleManifestRow
from ..deps import DbSession

router = APIRouter()


@router.get("/rulesets/{ruleset_id}", response_model=RulesetResponse)
async def get_ruleset(ruleset_id: str, db: DbSession) -> RulesetResponse:
    row = db.execute(
        select(RuleManifestRow).where(
            (RuleManifestRow.ruleset_id == ruleset_id) | (RuleManifestRow.hash == ruleset_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise LifecycleError(ErrorCode.NOT_FOUND, f"ruleset {ruleset_id} is not loaded")
    return RulesetResponse(manifest=RuleManifest.model_validate(row.payload))
