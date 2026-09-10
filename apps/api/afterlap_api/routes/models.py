"""Model bundle manifests and their measured approval state.

A candidate and an approved bundle are visibly different. Nothing here can
promote a bundle; promotion is a coordinator command with frozen thresholds.
"""

from __future__ import annotations

from sqlalchemy import select

from afterlap_contracts import ApprovalStatus, ModelManifest
from afterlap_contracts.requests import ModelListResponse

from ..db.models import ModelBundle
from ..deps import DbSession
from ..router import get


@get("/models")
async def list_models(
    db: DbSession,
    approval_status: ApprovalStatus | None = None,
) -> ModelListResponse:
    statement = select(ModelBundle).order_by(ModelBundle.created_at.desc())
    if approval_status is not None:
        statement = statement.where(ModelBundle.approval_status == approval_status.value)
    rows = db.execute(statement).scalars().all()
    return ModelListResponse(models=tuple(ModelManifest.model_validate(r.manifest) for r in rows))
