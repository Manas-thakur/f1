"""AFTERLAP domain core.

Sub-packages own disjoint concerns: ``data`` (ingestion and provenance),
``simulation`` (truth and physics), ``rules`` (regulatory checks),
``estimation`` (beliefs), ``planning`` (candidates), ``learning`` (SAC and
continuation value) and ``evaluation`` (benchmarks).

No module here has an HTTP dependency; the API package adapts these to routes.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
