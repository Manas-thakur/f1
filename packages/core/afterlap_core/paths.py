from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Paths:
    configs: Path

    @classmethod
    def default(cls) -> Paths:
        for parent in Path(__file__).resolve().parents:
            if (parent / "configs/race-circuits").is_dir():
                return cls(parent / "configs")
        raise RuntimeError("could not locate simulator configurations")


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
