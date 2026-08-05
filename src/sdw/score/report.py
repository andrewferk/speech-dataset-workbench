"""The Report: the Evaluation Scope, the N-of-M disclosure, and the fixed sentences above them.

One Report, two renderings (:mod:`sdw.score.digest`, :mod:`sdw.score.document`) — same Scope, same
counts, same disclosures, different resolution (ADR-0022). Everything either rendering says is
assembled here, so the two cannot drift into disagreeing about what was measured.

The Report is a pure function of the Run, the Scope and the tool: it may quote any fact the Run
recorded and may not observe one of its own, which is what makes two Reports diffable and #138's
goldens well-defined (ADR-0022 as narrowed by ADR-0024).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sdw import __version__
from sdw.score.run import SPLIT_ORDER, Run
from sdw.score.text_normalization import TIER_A, TIER_B

# ADR-0022 header item 3: the map's named ceiling, stated as a property of the measurement.
REFERENCE_NOTE = (
    "the Prompt — so every number below measures recognition error plus speaker deviation, "
    "and a Sample where the speaker departed from the Prompt scores as an error"
)

# ADR-0022 header item 4 (ADR-0024). The last sentence concedes an unmeasured floor and reads like
# hedging to cut; the tier headings below the header carry the rest of the rule.
COMPARABILITY_NOTE = (
    "compare only Runs of equal Scope; once a model has trained on train, only test is honest. "
    "The comparison this number exists for is paired against a Run over the same Samples, and "
    "rests on a run-to-run non-determinism floor this project has not measured."
)


@dataclass(frozen=True)
class Report:
    """What both renderings print. Counts are over the Scope, never over the whole Record."""

    splits: tuple[str, ...]
    selected_split: str | None
    in_scope: int
    scored: int
    failed: int
    long_form: int
    provenance: dict[str, Any]
    tool_version: str

    @property
    def scope_label(self) -> str:
        """ "test", or "train, val, test (every Split present)" — the Scope, always stated.

        A headline is only honest with its Scope attached, so the label follows `--split` rather
        than the Splits that happen to be in the Record (ADR-0017).
        """
        if self.selected_split is not None:
            return self.selected_split
        return f"{', '.join(self.splits)} (every Split present)"


def assemble(run: Run, *, split: str | None) -> Report:
    """Build the Report for ``run`` under the Evaluation Scope ``split`` (``None`` = every Split).

    Narrowing at Scoring is free, which is why it happens here and nowhere upstream (ADR-0017).
    """
    in_scope = [sample for sample in run.record if split is None or sample.split == split]
    failed = [sample for sample in in_scope if sample.failed]
    return Report(
        splits=_splits_present(run),
        selected_split=split,
        in_scope=len(in_scope),
        # Failed Samples are excluded from the Metrics and counted in the open, because the Samples
        # likeliest to fail are the quiet, atypical, hard ones (ADR-0017).
        scored=len(in_scope) - len(failed),
        failed=len(failed),
        long_form=sum(1 for sample in in_scope if sample.long_form),
        provenance=dict(run.provenance),
        tool_version=__version__,
    )


def _splits_present(run: Run) -> tuple[str, ...]:
    """Every Split the Record carries, ADR-0004's three first and anything else after.

    A Split the eval path does not recognise is still **listed**, because the label claims to name
    every Split present and a Sample counted in N-of-M but missing from the label would make that
    claim false. The order stays total: the known three in ADR-0004's order, then the rest by name.
    """
    present = {sample.split for sample in run.record}
    known = tuple(name for name in SPLIT_ORDER if name in present)
    return known + tuple(sorted(present - set(SPLIT_ORDER)))


def normalizers() -> tuple[str, str]:
    """The two Normalizer identity strings, in tier order (ADR-0018).

    Report-side attribution: `run.json` is written by `transcribe`, before any Text Normalization
    has happened, so these cannot come from the Run (ADR-0020).
    """
    return TIER_A, TIER_B
