"""Speech Dataset Workbench — a stateless, deterministic `--data-in` → `--data-out` transform."""

# The single version declaration; `pyproject.toml` derives its version from here (#37). It feeds the
# `dataset_version` preimage, so `tool_version` reads this source line, never `importlib.metadata` —
# a hash input must read the tree, not the install (ADR-0010).
__version__ = "0.1.0"
