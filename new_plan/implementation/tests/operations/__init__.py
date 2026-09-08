"""Operations drills: cold start, outage, restart, quota, hash, security, shutdown.

A package (not a bare directory) per coordinator decision D-03: two sibling
`conftest.py` files both import as the top-level module `conftest` under
pytest's prepend import mode, and whichever loads second shadows the first.
Fixtures here are imported relatively, `from .conftest import ...`.

Every test in this package **causes** the failure it is about. Where a drill
approximates instead, the docstring says so in its first paragraph and
`handoffs/A14.md` lists it. Nothing here asserts against a mock of a failure
the product would have handled differently in reality.
"""
