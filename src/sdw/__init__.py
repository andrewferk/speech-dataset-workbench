"""Speech Dataset Workbench — a stateless, deterministic `--data-in` → `--data-out` transform."""

# The workbench's own version string, and one of the three inputs to `dataset_version` (ADR-0010).
# ADR-0010 says "read from package metadata"; there is none to read, because the tool is never
# installed (`package = false`, ADR-0012) and runs as `python -m sdw` off the source tree, so
# `importlib.metadata` would raise. Declared here instead, with a test asserting it equals
# pyproject's `[project].version` so the two cannot drift.
#
# The dependency set is covered by convention rather than by the hash: `uv.lock` is committed, and
# the release rule is that any lock change ships a version bump.
__version__ = "0.1.0"
