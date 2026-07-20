"""ADR-0012 Check 3 — the audit recipe, run against the tool it documents (#36).

ADR-0010's central property is that `dataset_version` is **recomputable from `--data-out` alone**.
It then declined a `verify` command — issue #8's two-command spine should not grow a third for an
audit need a single user does not have. That call stands, and it makes the recipe **load-bearing
documentation**: the property is demonstrated nowhere but in prose, and prose nothing runs is prose
that is wrong within two releases.

This module runs the documented recipe (README, "Auditing a build — recomputing `dataset_version`")
against a committed `--data-out` and compares the result to the recorded id.

**It imports nothing from `src/`.** That constraint is the entire point. A test sharing the tool's
hashing code computes ``f(x) == f(x)`` and passes forever — including when `f` is wrong, and
including when the documented recipe describes something `f` does not do. Such a test is *worse than
no test*: the CI dashboard reads "verified" while it asserts nothing. So the preimage below is
re-spelled from its documented steps — the domain separator, the framing, the encoding, all literal
here — and checks the **documentation against the tool**, not the tool against itself.

Its failure mode is a feature. When it fails, it is genuinely ambiguous whether `src/` or the
README is wrong, which forces a human to decide rather than auto-update a golden. That is the
correct failure mode for a provenance claim. In particular, a preimage change in `src/` that
regenerates the committed golden (`UPDATE_GOLDEN`) moves the recorded id but **not** this
independent recipe — so this test goes red until the README and this file are brought back into
step. That coupling — recipe prose and this test edited together — is the mechanism ADR-0012 names.

The audited tree is the committed reference golden (`tests/fixtures/reference/golden/`): a real,
static `--data-out` snapshot, so the audit needs no build step and therefore no `src/` at all.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

# The committed reference `--data-out` snapshot (ADR-0008's golden). A static tree, so auditing it
# invokes nothing — no build, no import from the package under test.
GOLDEN_DIR = Path(__file__).parents[1] / "fixtures" / "reference" / "golden"

# The recipe's own constants, re-spelled from ADR-0010's documented preimage rather than imported.
# Importing `sdw.provenance.DOMAIN_SEPARATOR` here would reintroduce exactly the shared-code
# circularity this test exists to avoid.
DOMAIN_SEPARATOR = "sdw-dataset-version/1"
ENCODING = "utf-8"
HASH_PREFIX = "sha256:"
# ADR-0010 fixes the framing order train, val, test; an empty Split frames cleanly at length 0.
SPLIT_ORDER = ("train", "val", "test")


def _recompute_dataset_version(data_out: Path) -> str:
    """Recompute `dataset_version` from a `--data-out` alone, following the documented recipe.

    The literal steps from the README's "Auditing a build" recipe, reimplemented here with no
    reference to `src/`:

    1. Read `tool_version` and the `config` block from `dataset.json`.
    2. Re-serialize `config` canonically — keys sorted, compact separators, UTF-8 — reproducing the
       exact bytes the preimage hashed (`dataset.json` writes that subtree the same way).
    3. Frame each of `train`/`val`/`test.jsonl` as ``<name> <byte-length>\\n<raw bytes>`` in that
       fixed order, its raw bytes exactly as written to disk.
    4. Concatenate, behind the domain separator and the framed `tool_version` and `config`, sha256.
    """
    descriptor = json.loads((data_out / "dataset.json").read_text(encoding=ENCODING))
    tool_version = descriptor["tool_version"]
    # `separators` drops the whitespace `json.dumps` inserts by default; `sort_keys` and the config
    # subtree already being key-sorted make this byte-identical to the descriptor's `config` bytes.
    config_json = json.dumps(
        descriptor["config"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )

    hasher = hashlib.sha256()
    hasher.update(f"{DOMAIN_SEPARATOR}\n".encode(ENCODING))
    hasher.update(f"tool_version\n{tool_version}\n".encode(ENCODING))
    hasher.update(f"config\n{config_json}\n".encode(ENCODING))
    for name in SPLIT_ORDER:
        raw = (data_out / f"{name}.jsonl").read_bytes()
        hasher.update(f"{name}.jsonl {len(raw)}\n".encode(ENCODING))
        hasher.update(raw)
    return HASH_PREFIX + hasher.hexdigest()


def test_recipe_reproduces_the_recorded_dataset_version() -> None:
    # The audit's whole claim: the id independently recomputed from `--data-out` equals the id the
    # tool recorded. A mismatch means the README recipe and the tool have diverged — decide which.
    recorded = json.loads((GOLDEN_DIR / "dataset.json").read_text(encoding="utf-8"))[
        "dataset_version"
    ]
    assert _recompute_dataset_version(GOLDEN_DIR) == recorded


def test_recipe_imports_nothing_from_src() -> None:
    # The constraint made checkable, not just asserted in prose: parse this module and confirm no
    # `import sdw` / `from sdw import …` survives a careless edit. A shared-code version reads as
    # verified on the dashboard while computing `f(x) == f(x)` — worse than no test (ADR-0012).
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
    offenders = [name for name in imported if name == "sdw" or name.startswith("sdw.")]
    assert not offenders, f"audit recipe must be re-derived, not imported from src/: {offenders}"
