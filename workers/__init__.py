"""Process entry points.

``session_worker`` owns one session's dynamics; ``batch_worker`` claims bounded
experiment jobs. Neither contains lifecycle rules: they are thin composition
roots over :mod:`afterlap_application` and :mod:`afterlap_infrastructure`.
"""

from __future__ import annotations

__all__: list[str] = []
