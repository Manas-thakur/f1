"""Keep server-side filesystem layout out of the wire.

A refusal has to say *which* artefact it could not use, and the loaders phrase
that with the path they tried. Those paths are absolute and describe the
deployment: ``/app/artifacts/...`` in a container, ``/Users/<name>/...`` on a
laptop. Neither is information a client can act on, and both describe a machine
rather than an artefact.

So a path is rewritten to the part that identifies the artefact --
``artifacts/tracks/monza/package.json`` -- and anything outside a known root is
elided entirely. Hashes, source URLs, licence text and readiness reasons are
untouched: they are the evidence the catalogue exists to carry.
"""

from __future__ import annotations

import re
from os import fspath
from pathlib import Path

ARTEFACT_ROOTS = ("artifacts", "configs")
"""Path segments that make the remainder of a path meaningful to a client."""

ELIDED = "<local path>"

_ABSOLUTE_PATH = re.compile(
    r"(?:"
    r"(?<![\w:/\\])[A-Za-z]:[\\/][^\s'\"<>,;)]*"
    r"|(?<![\w:/\\])\\\\[^\s'\"<>,;)]*[\\/][^\s'\"<>,;)]*"
    r"|(?<![\w:/])/[^\s'\"<>,;)]*(?:/[^\s'\"<>,;)]*)+"
    r")"
)
_TRAILING = ".:;,)]}'\""


def artefact_relative(path: str | Path) -> str | None:
    """The artefact-identifying tail of ``path``, or ``None`` when it has none.

    ``/app/artifacts/exports/exp-1.json`` becomes ``artifacts/exports/exp-1.json``:
    enough for an operator to find the file in the deployment they administer,
    and nothing about where that deployment happens to be installed.
    """
    parts = tuple(part for part in fspath(path).replace("\\", "/").split("/") if part)
    for root in ARTEFACT_ROOTS:
        if root in parts:
            return "/".join(parts[parts.index(root) :])
    return None


def scrub_local_paths(text: str) -> str:
    """Rewrite every absolute path in ``text``; leave URLs and hashes alone."""

    def replace(match: re.Match[str]) -> str:
        found = match.group(0)
        trailing = ""
        while found and found[-1] in _TRAILING:
            trailing = found[-1] + trailing
            found = found[:-1]
        return (artefact_relative(found) or ELIDED) + trailing

    return _ABSOLUTE_PATH.sub(replace, text)


__all__ = ["ARTEFACT_ROOTS", "ELIDED", "artefact_relative", "scrub_local_paths"]
