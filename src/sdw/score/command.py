"""`sdw score`: read one Run directory, print the Evaluation Report, write nothing (ADR-0021).

Purity is a property of the command surface, not of an inner function: there is no dataset argument
to pass, so there is no way to make Scoring impure by accident (ADR-0017). The Report goes to
stdout and is never persisted — an operator who wants to keep one redirects it, and that file is
honestly theirs rather than an artifact the tool implies it maintains.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sdw.score import digest, document, report, run
from sdw.score.report import Report

# The two renderings of one Report (ADR-0022). `sdw.cli` names the same two tokens as `--format`'s
# choices, because it may not import this module to build the parser (ADR-0023) — the e2e suite runs
# both, so a token present in one place and not the other fails there.
RENDERINGS: dict[str, Callable[[Report], str]] = {
    "text": digest.render,
    "json": document.render,
}


def score(*, run_dir: Path, split: str | None, output_format: str) -> None:
    """Score the Run at ``run_dir`` under Scope ``split`` and print the Report.

    ``output_format`` selects a rendering of one Report — it changes no Metric, no Scope and nothing
    reaching durable identity, which is why it is not configuration (ADR-0022).
    """
    assembled = report.assemble(run.read(run_dir), split=split)
    print(RENDERINGS[output_format](assembled), end="")
