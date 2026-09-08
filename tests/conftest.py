from __future__ import annotations

import importlib.util

collect_ignore: list[str] = []
if importlib.util.find_spec("gymnasium") is None or importlib.util.find_spec("torch") is None:
    collect_ignore.append("learning")
