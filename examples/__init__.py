"""The example corpus and its generator (ADR-0009).

A package only so ``examples.generate`` is importable by the drift test and typecheckable by mypy,
mirroring ``tests/__init__.py``. Dev-time only — nothing shipped depends on this tree.
"""
