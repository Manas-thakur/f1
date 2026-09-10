"""Immutable rule pack manifests and their honest coverage."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from sqlalchemy import select

from afterlap_contracts import ErrorCode, RuleManifest
from afterlap_contracts.requests import RulesetResponse
from afterlap_core.rules import list_rule_packs, load_rule_pack

from ..db import LifecycleError
from ..db.models import RuleManifestRow
from ..deps import DbSession
from .catalog import catalogue_paths

if TYPE_CHECKING:
    from afterlap_core.paths import Paths
    from afterlap_core.rules import RulePack

router = APIRouter()


@router.get("/rulesets/{ruleset_id}", response_model=RulesetResponse)
async def get_ruleset(ruleset_id: str, request: Request, db: DbSession) -> RulesetResponse:
    """Resolve a pack by id or by content hash.

    The store is asked first, because a pack pinned by a session is the exact
    document that session was checked against and it must not be re-read from
    a file that may have changed since. A pack no session has used yet is not
    "not loaded": it is a reviewed document sitting in ``configs/rules``, and
    refusing it makes the pack a session would be created from unreadable
    before the first session exists.
    """
    row = db.execute(
        select(RuleManifestRow).where(
            (RuleManifestRow.ruleset_id == ruleset_id) | (RuleManifestRow.hash == ruleset_id)
        )
    ).scalar_one_or_none()
    if row is not None:
        return RulesetResponse(manifest=RuleManifest.model_validate(row.payload))

    paths = catalogue_paths(request)
    pack = pack_on_disk(ruleset_id, paths)
    if pack is None:
        available = ", ".join(list_rule_packs(paths)) or "none"
        raise LifecycleError(
            ErrorCode.NOT_FOUND,
            f"ruleset {ruleset_id} is not loaded and no configured pack matches it",
            available=available,
        )
    return RulesetResponse(manifest=pack.manifest)


def pack_on_disk(ruleset_id: str, paths: Paths | None) -> RulePack | None:
    """The configured pack with this id, or whose manifest hashes to it.

    ``load_rule_pack`` builds ``configs/rules/<id>.yaml`` by concatenation, and
    ``ruleset_id`` arrives from a URL. So the id is never handed to the loader
    until it has matched an entry ``list_rule_packs`` enumerated: a request for
    anything outside that directory cannot name a file, it can only fail to
    match. A hash is compared against the candidates' own manifests for the
    same reason.
    """
    candidates = list_rule_packs(paths)
    if ruleset_id in candidates:
        return _load(ruleset_id, paths)
    for candidate in candidates:
        pack = _load(candidate, paths)
        if pack is not None and pack.ruleset_hash == ruleset_id:
            return pack
    return None


def _load(candidate: str, paths: Paths | None) -> RulePack | None:
    try:
        return load_rule_pack(candidate, paths)
    except (OSError, ValueError):
        return None
