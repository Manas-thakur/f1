"""Process entry points.

``session_worker`` owns one session's dynamics; ``batch_worker`` claims bounded
experiment jobs. Neither contains lifecycle rules: they are launchers around
:mod:`afterlap_api.session` and the coordinator's persistence layer.
"""

from __future__ import annotations

__all__: list[str] = []
