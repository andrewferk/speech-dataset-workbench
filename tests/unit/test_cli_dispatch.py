"""Dispatch is lazy: `sdw.cli` imports no command module at module level (ADR-0023).

Checked from the other side — what `cli.py` imports at module level must stay within the
non-command modules named below — so a command added eagerly and never lazily, which is the
erosion itself, fails here rather than going unnoticed.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import sdw
from sdw.cli import main

CLI_SOURCE = Path(sdw.__file__).parent / "cli.py"

# Every `sdw.*` module `cli.py` may import at module level. A command module added here is the
# violation this file exists to catch, so extending it is a decision, not a fix (ADR-0023).
NON_COMMAND_MODULES = frozenset({"sdw.errors"})


def _sdw_modules(node: ast.AST) -> set[str]:
    """The `sdw.*` modules one import statement names, relative forms resolved.

    `cli.py` sits directly under `sdw`, so any relative import in it is rooted there.
    """
    if isinstance(node, ast.Import):
        return {alias.name for alias in node.names if alias.name.startswith("sdw.")}
    if not isinstance(node, ast.ImportFrom):
        return set()
    module = node.module if node.level == 0 else f"sdw.{node.module}" if node.module else "sdw"
    if module == "sdw":
        return {f"sdw.{alias.name}" for alias in node.names}
    return {module} if module and module.startswith("sdw.") else set()


def _imported_sdw_modules(*, nested: bool) -> set[str]:
    """The `sdw.*` modules `cli.py` imports inside a function body (`nested=True`) or at
    module level (`nested=False`)."""
    tree = ast.parse(CLI_SOURCE.read_text())
    in_function = {
        node
        for parent in ast.walk(tree)
        if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef)
        for node in ast.walk(parent)
    }
    modules: set[str] = set()
    for node in ast.walk(tree):
        if (node in in_function) is nested:
            modules |= _sdw_modules(node)
    return modules


def _modules_loaded_by(probe: str) -> set[str]:
    """Everything in `sys.modules` after running `probe` in a fresh interpreter."""
    result = subprocess.run(
        [sys.executable, "-c", f"{probe}\nimport sys; print('\\n'.join(sorted(sys.modules)))"],
        capture_output=True,
        text=True,
        check=True,
    )
    return set(result.stdout.split())


COMMAND_MODULES = sorted(_imported_sdw_modules(nested=True))


def test_the_cli_imports_no_command_module_at_module_level() -> None:
    assert _imported_sdw_modules(nested=False) <= NON_COMMAND_MODULES


def test_every_command_has_a_dispatch_branch_import() -> None:
    # Guards the parametrized tests below, which are vacuous over an empty list.
    assert COMMAND_MODULES


@pytest.mark.parametrize("module", COMMAND_MODULES)
def test_importing_the_cli_pulls_in_no_command_module(module: str) -> None:
    # Transitive, and over the real import: a command module reached through some other
    # module-level import passes the AST check above and still costs `--help` the load.
    assert module not in _modules_loaded_by("import sdw.cli")


@pytest.mark.parametrize("module", COMMAND_MODULES)
def test_the_parser_is_built_without_importing_a_command_module(module: str) -> None:
    assert module not in _modules_loaded_by("from sdw.cli import _parser; _parser()")


@pytest.mark.parametrize(
    "argv",
    [[], ["build"], ["validate"], ["transcribe"]],
    ids=["sdw", "build", "validate", "transcribe"],
)
def test_help_exits_zero(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main([*argv, "--help"])
    assert exc.value.code == 0
