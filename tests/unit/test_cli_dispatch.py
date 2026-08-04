"""Dispatch is lazy: `sdw.cli` imports no command module at module level (ADR-0023).

The rule is uniform across every command, so it has no sanctioned exception to erode. These
tests derive the command modules from `cli.py` itself rather than naming them, so a command
added later is covered without editing this file (ADR-0010).
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import sdw
from sdw.cli import main

CLI_SOURCE = Path(sdw.__file__).parent / "cli.py"


def _sdw_imports(depth: str) -> set[str]:
    """The `sdw.*` modules `cli.py` imports at module level (`depth="module"`) or inside a
    function body (`depth="function"`)."""
    tree = ast.parse(CLI_SOURCE.read_text())
    nested = {
        node
        for parent in ast.walk(tree)
        if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef)
        for node in ast.walk(parent)
    }
    names: set[str] = set()
    for node in ast.walk(tree):
        if depth == "function" and node not in nested:
            continue
        if depth == "module" and node in nested:
            continue
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                qualified = f"{node.module}.{alias.name}"
                if node.module == "sdw":
                    names.add(qualified)
                elif node.module.startswith("sdw."):
                    names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names if a.name.startswith("sdw."))
    return names


COMMAND_MODULES = sorted(_sdw_imports("function"))


def test_there_is_at_least_one_dispatch_branch_import() -> None:
    # Guards the two tests below: they are vacuous if the derivation finds nothing.
    assert COMMAND_MODULES


@pytest.mark.parametrize("module", COMMAND_MODULES)
def test_a_command_module_is_not_also_imported_at_module_level(module: str) -> None:
    assert module not in _sdw_imports("module")


def test_importing_the_cli_pulls_in_no_command_module() -> None:
    # Transitive, and over the real import: a command module reached through some other
    # module-level import would satisfy the AST check above and still cost `--help` the load.
    probe = "import sdw.cli, sys; print('\\n'.join(sorted(sys.modules)))"
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    loaded = set(result.stdout.split())
    assert not loaded.intersection(COMMAND_MODULES)


def test_the_parser_is_built_without_importing_a_command_module() -> None:
    probe = (
        "from sdw.cli import _parser; import sys; _parser(); print('\\n'.join(sorted(sys.modules)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    loaded = set(result.stdout.split())
    assert not loaded.intersection(COMMAND_MODULES)


@pytest.mark.parametrize("argv", [[], ["build"], ["validate"]], ids=["sdw", "build", "validate"])
def test_help_exits_zero(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main([*argv, "--help"])
    assert exc.value.code == 0
