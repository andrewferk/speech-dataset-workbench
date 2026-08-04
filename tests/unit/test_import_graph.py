"""The import boundary: three rules over `sdw.*` module prefixes, checked by AST (ADR-0023).

The map's founding claim about v0.2 is that isolation is **structural, not aspirational**. Exactly
one of the three rules is genuinely structural — `sdw.score` importing anything behind the `asr`
extra is an `ImportError` in the CI job that installs no extra, which is why that job may never gain
it. The other two are same-distribution, zero-dependency imports that would work perfectly and break
nothing at runtime, so they get this check: ADR-0012's bar met one notch below its ideal, because
for these two there is no notch above.

`import-linter` cannot express what is checked here. It treats a module-level import and a
function-body import as one edge, and the distinction between them is the mechanism keeping
`sdw --help` alive in a torch-free venv — so edges are tagged by node depth, and a violation reports
the *path* rather than the fact.

The `sdw.transcribe` clauses hold vacuously until that subpackage exists. That is deliberate: the
rules are stated in full now, so the boundary is a check the first transcribe module meets rather
than one someone remembers to extend.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import pytest

import sdw

PACKAGE_ROOT = Path(sdw.__file__).parent
PACKAGE = "sdw"

PIPELINE = "sdw.pipeline"
TRANSCRIBE = "sdw.transcribe"
SCORE = "sdw.score"
FORBIDDEN_TO_EVAL = ("sdw.manifest", "sdw.provenance")


class Edge(NamedTuple):
    """One import, tagged by the depth of the node that made it.

    ``nested`` is true for an import inside a function or method — sanctioned in `sdw.cli`'s
    dispatch branches, and rule 3's likeliest violation everywhere else.
    """

    importer: str
    imported: str
    nested: bool

    def __str__(self) -> str:
        return f"{self.imported} ({'nested' if self.nested else 'module-level'})"


def _module_name(path: Path) -> str:
    parts = path.relative_to(PACKAGE_ROOT).with_suffix("").parts
    trimmed = parts[:-1] if parts[-1] == "__init__" else parts
    return ".".join((PACKAGE, *trimmed))


def _imports(node: ast.AST, module: str) -> Iterator[str]:
    """The `sdw.*` modules one import statement names, relative forms resolved."""
    package = module if _is_package(module) else module.rsplit(".", 1)[0]
    if isinstance(node, ast.Import):
        yield from (alias.name for alias in node.names if alias.name.startswith(f"{PACKAGE}."))
        return
    if not isinstance(node, ast.ImportFrom):
        return
    if node.level:
        # `from . import x` / `from .y import z`, resolved against the importer's own package.
        base = ".".join(package.split(".")[: len(package.split(".")) - node.level + 1])
        base = f"{base}.{node.module}" if node.module else base
    else:
        base = node.module or ""
    if not base.startswith(PACKAGE):
        return
    # `from sdw.score import digest` names a module; `from sdw.score.run import Sample` names a
    # symbol. Both forms are emitted — an edge to a name that is not a module is inert.
    yield base
    yield from (f"{base}.{alias.name}" for alias in node.names)


def _is_package(module: str) -> bool:
    return (PACKAGE_ROOT / Path(*module.split(".")[1:]) / "__init__.py").is_file()


def _parse() -> tuple[set[Edge], set[str]]:
    """Every intra-`sdw` import in the source tree, tagged by node depth, and every module parsed.

    The two are returned together because they must come from one walk: a module set derived from
    the *edges* would omit every module that imports nothing, so "parses every module" would be a
    claim about the graph rather than about the tree (ADR-0023).
    """
    edges: set[Edge] = set()
    modules: set[str] = set()
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        module = _module_name(path)
        modules.add(module)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        in_function = {
            node
            for parent in ast.walk(tree)
            if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef)
            for node in ast.walk(parent)
        }
        for node in ast.walk(tree):
            nested = node in in_function
            edges |= {Edge(module, imported, nested) for imported in _imports(node, module)}
    return edges, modules


EDGES, MODULES = _parse()


def _under(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def _path_to(sources: tuple[str, ...], targets: tuple[str, ...]) -> list[Edge] | None:
    """The first path from anything under ``sources`` to anything under ``targets``, or ``None``.

    Breadth-first over the whole intra-package graph, so a violation reached through three
    innocent-looking modules is found and reported as the chain it is.
    """
    queue: list[tuple[str, list[Edge]]] = [
        (module, [])
        for module in sorted(MODULES)
        if any(_under(module, source) for source in sources)
    ]
    seen = {module for module, _ in queue}
    while queue:
        module, trail = queue.pop(0)
        for edge in sorted(edge for edge in EDGES if edge.importer == module):
            if any(_under(edge.imported, target) for target in targets):
                return [*trail, edge]
            if edge.imported not in seen and edge.imported in MODULES:
                seen.add(edge.imported)
                queue.append((edge.imported, [*trail, edge]))
    return None


def _report(path: list[Edge]) -> str:
    return " → ".join([path[0].importer, *(str(edge) for edge in path)])


def test_every_module_under_src_is_parsed() -> None:
    # Guards the three rules below, each of which is vacuous over a graph missing its nodes. The
    # vendored tree is parsed too: excluded from ruff and mypy (pyproject.toml), it is still source
    # under `sdw.score`, and an import out of it would break the boundary like any other.
    discovered = {
        ".".join((PACKAGE, *path.relative_to(PACKAGE_ROOT).with_suffix("").parts)).removesuffix(
            ".__init__"
        )
        for path in PACKAGE_ROOT.rglob("*.py")
    }

    assert discovered == MODULES
    assert {"sdw.cli", "sdw.errors", "sdw.pipeline", "sdw.score.run"} <= MODULES


def test_the_build_path_imports_nothing_from_the_eval_path() -> None:
    # Rule 1: `sdw.pipeline`'s transitive closure reaches neither evaluation subpackage. A
    # separate distribution would have made this structural; it also would have made rule 3 easier
    # to violate, which is the boundary that actually needs help (ADR-0023).
    violation = _path_to((PIPELINE,), (TRANSCRIBE, SCORE))
    assert violation is None, f"build path reaches the eval path: {_report(violation or [])}"


def test_scoring_imports_nothing_from_transcription() -> None:
    # Rule 2, which the `check` CI job supplies structurally by installing no extra. Stated here
    # anyway: an intra-package import needs no torch to resolve, so the job would stay green.
    violation = _path_to((SCORE,), (TRANSCRIBE,))
    assert violation is None, f"Scoring reaches Transcription: {_report(violation or [])}"


@pytest.mark.parametrize("eval_path", [TRANSCRIBE, SCORE], ids=["transcribe", "score"])
def test_the_eval_path_imports_no_manifest_or_provenance_module(eval_path: str) -> None:
    # Rule 3, the stranger-consumer dogfood: the eval path parses the emitted JSONL itself, so an
    # under-specified Manifest is caught by the code reading it rather than papered over by a
    # shared constant. `sdw.serialization` is the one permitted import (ADR-0019).
    violation = _path_to((eval_path,), FORBIDDEN_TO_EVAL)
    assert violation is None, (
        f"{eval_path} reaches the build path's readers: {_report(violation or [])}"
    )


def test_the_eval_path_may_import_the_shared_serialization_module() -> None:
    # The permission is asserted, not merely unenforced: a future tightening of rule 3 that swept
    # `sdw.serialization` in would re-create the byte-format drift ADR-0006 exists to prevent.
    assert _path_to((SCORE,), ("sdw.serialization",)) is not None
