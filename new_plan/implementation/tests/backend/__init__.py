"""Backend session-runtime and integration tests (A08).

A package, not a bare directory: coordinator decision D-03 requires every test
directory to carry an ``__init__.py`` and import its fixtures relatively, so two
sibling ``conftest.py`` files cannot shadow each other under pytest's prepend
import mode.
"""
