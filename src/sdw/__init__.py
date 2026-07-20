"""Speech Dataset Workbench — a stateless, deterministic `--data-in` → `--data-out` transform."""

# The workbench's own version string, and one of the three inputs to `dataset_version` (ADR-0010).
# Declared here rather than read from package metadata, with a test asserting it equals pyproject's
# `[project].version` so the two cannot drift. ADR-0014 made `importlib.metadata` available, but it
# reports what `.dist-info` recorded at install time: a bumped version without a re-sync would mint
# ids under the stale string. A hash input reads the tree. #37 removes the remaining duplication by
# having pyproject derive its version from here, not the reverse.
#
# The dependency set is covered by convention rather than by the hash: `uv.lock` is committed, and
# the release rule is that any lock change ships a version bump.
__version__ = "0.1.0"
