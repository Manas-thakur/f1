from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool:
    if importlib.util.find_spec("gymnasium") is not None and importlib.util.find_spec("torch") is not None:
        return False
    try:
        collection_path.resolve().relative_to(Path(config.rootpath) / "tests" / "learning")
    except ValueError:
        return False
    return True
