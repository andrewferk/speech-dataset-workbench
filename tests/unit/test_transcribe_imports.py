"""`sdw.transcribe` reads the dataset as a stranger, and needs no ASR extra to be imported (#164).

Two of ADR-0023's rules, asserted over the modules that exist today: nothing under `sdw.transcribe`
reaches `sdw.manifest` or `sdw.provenance` at any depth, and every module in the subpackage imports
in a venv with no `asr` extra installed. Both are structural analysis rather than a structural
impossibility, which ADR-0023 argues is the best available here — a convenience import of
`SPLIT_ORDER` would work perfectly and break nothing at runtime, which is exactly why it needs a
check.

**#165 replaces this file with the AST import graph** ADR-0023 specifies: edges tagged by node
depth, rules phrased over module prefixes, and the violating *path* reported rather than the fact.
What is here is the same two rules restricted to this ticket's modules, so they are enforced from
the commit that creates them rather than from the one after.
"""

from __future__ import annotations

import pkgutil
import subprocess
import sys

import pytest

import sdw.transcribe

# Interpreting the dataset through v0.1's own modules is the shortcut that kills the dogfood: an
# under-specified Manifest would be read correctly by construction and nobody would find out.
FORBIDDEN = ("sdw.manifest", "sdw.provenance")

MODULES = sorted(module.name for module in pkgutil.iter_modules(sdw.transcribe.__path__))


def _modules_loaded_by(probe: str) -> set[str]:
    result = subprocess.run(
        [sys.executable, "-c", f"{probe}\nimport sys; print('\\n'.join(sorted(sys.modules)))"],
        capture_output=True,
        text=True,
        check=True,
    )
    return set(result.stdout.split())


def test_the_subpackage_has_modules_to_check() -> None:
    # Guards the parametrized tests below, which are vacuous over an empty list.
    assert MODULES


@pytest.mark.parametrize("module", MODULES)
def test_a_transcribe_module_reaches_no_v0_1_manifest_module(module: str) -> None:
    loaded = _modules_loaded_by(f"import sdw.transcribe.{module}")
    assert not [name for name in loaded if name.startswith(FORBIDDEN)]


@pytest.mark.parametrize("module", MODULES)
def test_a_transcribe_module_imports_without_the_asr_extra(module: str) -> None:
    # This ticket's modules are all model-free; #166 adds the one leaf that is not, and the check
    # narrows to "every other module" then (ADR-0025).
    loaded = _modules_loaded_by(f"import sdw.transcribe.{module}")
    assert not [name for name in loaded if name in {"torch", "transformers"}]
