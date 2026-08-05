"""ADR-0023's three import rules, as an AST graph over `src/sdw/` (#165).

The first test in the repo that reads source rather than running it. Rules 1 and 3 cannot be made
structural — `sdw.pipeline` importing `sdw.score.metrics`, and `sdw.transcribe` importing
`SPLIT_ORDER`, are same-distribution zero-dependency imports that would work perfectly and break
nothing at runtime — so they get a check, ADR-0012's bar met one notch below its ideal because for
these two there is no notch above.

Edges are tagged module level or function body. That distinction is why `import-linter` could not
express these rules, and why the subprocess `sys.modules` probe this file replaces was rejected: it
is blind to the function-body import ADR-0023 sanctions in `cli.py`, which is also rule 3's most
likely violation. The rules below count both kinds; the module-level-only view is
`test_cli_dispatch.py`'s.

Rule 2 is already structural — the `check` CI job installs no extra, so a module-level `import
torch` under `sdw.score` reddens the whole suite there — and is asserted anyway, because a rule
held only by the shape of a workflow file is a rule nobody reads.
"""

from __future__ import annotations

import ast
from collections import deque
from collections.abc import Sequence
from pathlib import Path

import pytest

import sdw

PACKAGE = "sdw"
ROOT = Path(sdw.__file__).parent

MODULE_LEVEL = "module level"
FUNCTION_BODY = "function body"

# Interpreting the dataset through v0.1's own modules is the shortcut that kills the dogfood: an
# under-specified Manifest would be read correctly by construction and nobody would find out
# (ADR-0017). `sdw.serialization` is not on this list — byte-format of our own output is not dataset
# interpretation (ADR-0019).
V0_1_MANIFEST_MODULES = ("sdw.manifest", "sdw.provenance")

Graph = dict[str, set[tuple[str, str]]]


def _under(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def _module_name(path: Path) -> str:
    parts = path.relative_to(ROOT).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join((PACKAGE, *parts))


MODULES = {_module_name(path): path for path in sorted(ROOT.rglob("*.py"))}


def _nearest(dotted: str) -> str:
    """The module an imported name lives in: `sdw.errors.HardError` is an edge to `sdw.errors`."""
    parts = dotted.split(".")
    while parts and ".".join(parts) not in MODULES:
        parts.pop()
    return ".".join(parts)


def _absolute(node: ast.ImportFrom, *, source: str) -> str:
    """`node`'s module, with a relative form resolved against the module that wrote it."""
    if node.level == 0:
        return node.module or ""
    base = source if MODULES[source].name == "__init__.py" else source.rpartition(".")[0]
    for _ in range(node.level - 1):
        base = base.rpartition(".")[0]
    return f"{base}.{node.module}" if node.module else base


def _targets(node: ast.AST, *, source: str) -> set[str]:
    """The `sdw` modules one import statement reaches, or nothing for any other node."""
    if isinstance(node, ast.Import):
        return {_nearest(alias.name) for alias in node.names if _under(alias.name, PACKAGE)}
    if not isinstance(node, ast.ImportFrom):
        return set()
    module = _absolute(node, source=source)
    if not _under(module, PACKAGE):
        return set()
    # `from sdw.transcribe import audio` names a module and `from sdw.errors import HardError`
    # names a class inside one; `_nearest` collapses both to the module that holds them.
    return {_nearest(f"{module}.{alias.name}") for alias in node.names}


def _module_edges(source: str, path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nested = {
        node
        for parent in ast.walk(tree)
        if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef)
        for node in ast.walk(parent)
    }
    edges: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        tag = FUNCTION_BODY if node in nested else MODULE_LEVEL
        edges |= {(target, tag) for target in _targets(node, source=source) if target}
    return edges


GRAPH: Graph = {source: _module_edges(source, path) for source, path in MODULES.items()}


def _violation(start: str, forbidden: Sequence[str], graph: Graph = GRAPH) -> str | None:
    """The shortest import path from `start` into `forbidden`, rendered, or `None` if there is none.

    The path, not the fact: `sdw.pipeline → sdw.staging → sdw.score.metrics` names the import to
    delete, where "rule 1 failed" leaves a reader to rebuild the graph by hand.
    """
    queue = deque([(start, start)])
    seen = {start}
    while queue:
        module, trail = queue.popleft()
        for target, tag in sorted(graph.get(module, set())):
            step = f"{trail} → {target}" + (f" [{tag}]" if tag == FUNCTION_BODY else "")
            if any(_under(target, prefix) for prefix in forbidden):
                return step
            if target not in seen:
                seen.add(target)
                queue.append((target, step))
    return None


def _modules_under(prefix: str) -> list[str]:
    return sorted(name for name in MODULES if _under(name, prefix))


EVAL_MODULES = _modules_under("sdw.transcribe") + _modules_under("sdw.score")


def test_the_graph_covers_the_package() -> None:
    # Guards every rule below, each of which is vacuous over an empty or truncated module set.
    assert {"sdw.cli", "sdw.pipeline", "sdw.transcribe.pipeline", "sdw.score.metrics"} <= set(
        MODULES
    )
    assert EVAL_MODULES


def test_a_module_level_import_is_an_edge() -> None:
    assert ("sdw.serialization", MODULE_LEVEL) in GRAPH["sdw.transcribe.record"]


def test_a_function_body_import_is_an_edge_tagged_as_one() -> None:
    # The whole reason this file parses source instead of watching `sys.modules`: the dispatch
    # branch import in `cli.py` is invisible to a runtime probe (ADR-0023).
    assert ("sdw.transcribe.pipeline", FUNCTION_BODY) in GRAPH["sdw.cli"]
    assert ("sdw.transcribe.pipeline", MODULE_LEVEL) not in GRAPH["sdw.cli"]


def test_a_planted_violation_is_found_and_reported_as_a_path() -> None:
    planted: Graph = {
        "sdw.pipeline": {("sdw.staging", MODULE_LEVEL)},
        "sdw.staging": {("sdw.score.metrics", FUNCTION_BODY)},
    }
    assert (
        _violation("sdw.pipeline", ("sdw.score",), planted)
        == "sdw.pipeline → sdw.staging → sdw.score.metrics [function body]"
    )


def test_the_build_path_reaches_nothing_under_the_eval_path() -> None:
    """Rule 1: `sdw.pipeline`'s transitive closure imports no Transcription or Scoring module."""
    found = _violation("sdw.pipeline", ("sdw.transcribe", "sdw.score"))
    assert found is None, found


@pytest.mark.parametrize("module", _modules_under("sdw.score"))
def test_scoring_reaches_nothing_under_transcription(module: str) -> None:
    """Rule 2: yesterday's Run is re-scorable on a machine that cannot transcribe (ADR-0017)."""
    found = _violation(module, ("sdw.transcribe",))
    assert found is None, found


@pytest.mark.parametrize("module", EVAL_MODULES)
def test_the_eval_path_reaches_no_v0_1_manifest_module(module: str) -> None:
    """Rule 3: Transcription and Scoring read the emitted files like a stranger (ADR-0017)."""
    found = _violation(module, V0_1_MANIFEST_MODULES)
    assert found is None, found
