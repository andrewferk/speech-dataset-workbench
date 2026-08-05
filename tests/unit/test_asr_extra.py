"""Absence of the `asr` extra is probed, and a genuine `ImportError` is not absence (#165).

The two facts must never be conflated (ADR-0023), so they are tested against each other: the same
command, one venv shape apart, must produce an operator-facing one-line fix in one case and a
traceback in the other. Both are forced rather than observed — the suite runs in a venv with the
extra and in one without, and a test that only holds in one of them is worse than no test.
"""

from __future__ import annotations

import importlib.metadata
import re
import sys

import pytest

import sdw.transcribe
from sdw import cli
from sdw.cli import main

ARGV = ["transcribe", "--dataset", "/nonexistent/dataset", "--eval-out", "/nonexistent/out"]


@pytest.fixture
def without_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """A venv the probe cannot find the extra in, whatever this one has installed."""
    monkeypatch.setattr(cli, "ASR_MODULES", ("sdw_asr_extra_that_is_not_installed",))


@pytest.fixture
def with_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """A venv the probe is satisfied by, whatever this one has installed."""
    monkeypatch.setattr(cli, "ASR_MODULES", ("sys",))


def test_the_missing_extra_is_a_hard_error(
    without_extra: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(ARGV) == 1
    assert capsys.readouterr().err.startswith("error: sdw transcribe needs the ASR extra")


def test_the_missing_extra_names_both_installs(
    without_extra: None, capsys: pytest.CaptureFixture[str]
) -> None:
    # Both, because the fix differs by how the operator installed and the tool cannot tell which
    # they are: a checkout gets one line and an install the other (ADR-0023).
    assert main(ARGV) == 1
    err = capsys.readouterr().err
    assert "uv sync --extra asr" in err
    assert "pip install 'sdw[asr]'" in err


def test_the_probe_runs_ahead_of_argument_validation(
    without_extra: None, capsys: pytest.CaptureFixture[str]
) -> None:
    # `--dataset` does not exist either. The extra is what gets reported, which is what "earliest
    # preflight" means in practice.
    assert main(ARGV) == 1
    err = capsys.readouterr().err
    assert "ASR extra" in err
    assert "/nonexistent/dataset" not in err


def test_an_internal_import_error_is_not_reported_as_a_missing_extra(
    with_extra: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The distinction itself: the probe passes, the dispatch import fails, and it propagates.

    A `try: … except ImportError:` around the dispatch import would turn this into the missing-extra
    message — a confident diagnosis pointing at the one thing that is not wrong (ADR-0023).
    """
    monkeypatch.delattr(sdw.transcribe, "pipeline", raising=False)
    monkeypatch.setitem(sys.modules, "sdw.transcribe.pipeline", None)
    with pytest.raises(ImportError):
        main(ARGV)


def test_the_probe_names_every_module_the_extra_provides() -> None:
    """Held against the declared extra, never restated: a second literal cannot catch drift.

    `find_spec` takes import names and the metadata declares distribution names, so the probe list
    cannot be derived from the extra — but a distribution added to `asr` and not to the list is the
    half-installed venv the probe exists to diagnose, silently unprobed (ADR-0010, ADR-0023). Where
    the two names differ, this fails and the divergence gets written down rather than discovered.
    """
    declared = {
        re.split(r"[\s;<>=!~\[]", requirement, maxsplit=1)[0]
        for requirement in importlib.metadata.metadata("sdw").get_all("Requires-Dist") or []
        if re.search(r"""extra\s*==\s*["']asr["']""", requirement)
    }
    assert declared == set(cli.ASR_MODULES)
