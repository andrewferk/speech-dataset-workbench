"""Speech Dataset Workbench — a stateless, deterministic `--data-in` → `--data-out` transform."""

# The workbench's own version string, and one of the three inputs to `dataset_version` (ADR-0010).
# This is the single declaration: `pyproject.toml` sets `dynamic = ["version"]` and derives it from
# here via `[tool.hatch.version]` (#37), so `importlib.metadata.version("sdw")` still answers
# correctly without a second literal to drift against. `tool_version` reads this source line rather
# than `importlib.metadata` on purpose: metadata reports what `.dist-info` recorded at install time,
# so a bumped version without a re-sync would mint ids under the stale string. A hash input reads
# the tree, not the install.
#
# The dependency set is covered by convention rather than by the hash: `uv.lock` is committed, and
# the release rule is that any lock change ships a version bump.
__version__ = "0.1.0"
