"""A02 ingestion tests.

This package marker matters: without it, a bare ``conftest.py`` here and one in
a sibling test directory both import as the top-level module ``conftest`` and
whichever loads second silently shadows the first. Making each test directory a
package gives them distinct module paths.
"""
