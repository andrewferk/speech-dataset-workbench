"""`sdw score`: read one Run directory, print the Evaluation Report, write nothing (ADR-0021).

Purity is a property of the command surface: there is no dataset argument to pass (ADR-0017).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sdw.score import digest, document, report, run
from sdw.score.report import Report

# `sdw.cli` repeats these two tokens as `--format`'s choices rather than importing them (ADR-0023);
# the e2e suite runs both, so a token added in one place and not the other fails there.
RENDERINGS: dict[str, Callable[[Report], str]] = {
    "text": digest.render,
    "json": document.render,
}


def score(*, run_dir: Path, split: str | None, output_format: str) -> None:
    """Score the Run at ``run_dir`` under Scope ``split`` and print the Report.

    ``output_format`` selects a rendering of one Report, and is not configuration (ADR-0022).
    """
    assembled = report.assemble(run.read(run_dir), split=split)
    print(RENDERINGS[output_format](assembled), end="")
