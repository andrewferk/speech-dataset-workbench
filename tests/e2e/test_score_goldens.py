"""The captured-stdout goldens: one Report per hand-authored Run fixture, compared exactly.

ADR-0008's *golden-file exact equality* with the one change ADR-0025 makes to it — the artifact
compared is a **stream**, because ADR-0021 never writes a Report to disk. Exact means exact: no
tolerance, no per-field comparison, no substituted `tool_version`. A test that needed a tolerance
would be evidence the artifact is not as deterministic as ADR-0022 claims, which is the claim these
files exist to hold.

**These files are where ADR-0022's cross-machine claim is actually asserted.** A Report is
byte-identical given the same Run, Scope and tool — a property no single-process comparison can
show, because both halves run on one machine. A committed golden authored on one platform and
compared in CI on another does show it, once per push, which is why the goldens run in the `check`
job rather than only where they were written (ADR-0025).

The expected values are hand-computed from the normalized strings each fixture names — see
`tests/fixtures/runs/README.md`, which records them and the one `jiwer` disagreement that is ours
by contract — so a red golden means the arithmetic moved, not that the code stopped agreeing with
itself.

A golden changes on a release, because ADR-0022's header carries the **scoring** `tool_version`
(ADR-0020's third occurrence). ADR-0025 accepts that churn under one guard: regenerate, then read
the diff, and a diff touching anything but the version-bearing lines is a behavioural change to
investigate before tagging. There is deliberately no `--update-goldens` flag.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sdw.cli import main

RUNS = Path(__file__).parents[1] / "fixtures" / "runs"
GOLDEN = "golden/report.txt"

CASES = sorted(directory.name for directory in RUNS.iterdir() if (directory / GOLDEN).is_file())


@pytest.mark.parametrize("case", CASES)
def test_the_digest_matches_its_golden_byte_for_byte(
    case: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["score", "--run", str(RUNS / case)]) == 0

    assert capsys.readouterr().out == (RUNS / case / GOLDEN).read_text(encoding="utf-8")


def test_every_fixture_run_carries_a_golden() -> None:
    # The floor ADR-0018 fixed and ADR-0025/#162 extended is only a floor while every committed Run
    # is actually scored: a fixture added without a golden is coverage that silently does nothing.
    unscored = [
        directory.name
        for directory in sorted(RUNS.iterdir())
        if (directory / "run.json").is_file() and not (directory / GOLDEN).is_file()
    ]

    assert not unscored, f"Run fixture(s) with no captured golden: {unscored}"
