"""Report assembly: the Evaluation Scope, and the counts the N-of-M disclosure states.

Narrowing happens here and nowhere upstream — a Hypothesis you did not generate costs a full model
run, one you generated and did not score costs nothing (ADR-0017).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sdw import __version__
from sdw.score import report, run

RUNS = Path(__file__).parents[1] / "fixtures" / "runs"


def _report(fixture: str, split: str | None = None) -> report.Report:
    return report.assemble(run.read(RUNS / fixture), split=split)


def test_the_default_scope_is_every_split_present() -> None:
    assembled = _report("clean")

    assert assembled.selected_split is None
    assert assembled.splits == ("train", "val", "test")
    assert assembled.scope_label == "train, val, test (every Split present)"


def test_splits_are_labelled_in_adr_0004s_order_not_the_records() -> None:
    # The order is reimplemented in the eval path rather than imported, which is the whole of
    # ADR-0017's "including SPLIT_ORDER" rule; the Record's own order is by `id` (ADR-0019).
    assert _report("disclosures").splits == ("train", "test")


def test_a_split_the_eval_path_does_not_know_is_still_labelled(tmp_path: Path) -> None:
    # A Sample counted in N-of-M but missing from the Scope label would make "every Split present"
    # a false claim, which is the one thing the label exists to prevent (ADR-0017).
    directory = tmp_path / "run"
    shutil.copytree(RUNS / "clean", directory)
    record = directory / "hypotheses.jsonl"
    record.write_text(
        record.read_text(encoding="utf-8").replace('"split":"val"', '"split":"dev"'),
        encoding="utf-8",
    )

    assembled = report.assemble(run.read(directory), split=None)

    assert assembled.splits == ("train", "test", "dev")
    assert assembled.in_scope == 4


def test_split_narrows_the_scope_and_the_label_follows_it() -> None:
    assembled = _report("clean", split="test")

    assert assembled.scope_label == "test"
    assert (assembled.in_scope, assembled.scored) == (1, 1)


def test_the_counts_are_over_the_scope_not_the_record() -> None:
    assembled = _report("disclosures", split="train")

    # Two in Scope, one of which failed; the third Sample is in `test` and is not counted here.
    assert (assembled.in_scope, assembled.scored, assembled.failed) == (2, 1, 1)
    assert assembled.long_form == 1


def test_a_clean_run_still_carries_the_disclosure() -> None:
    assembled = _report("clean")

    assert (assembled.in_scope, assembled.scored) == (4, 4)
    assert (assembled.failed, assembled.long_form) == (0, 0)


def test_the_scoring_tool_version_is_this_tool_not_the_runs() -> None:
    # ADR-0020's third occurrence: built, transcribed, scored — and the scoring one *routinely*
    # differs, because a Record is designed to be scored again under a later tool.
    assembled = _report("clean")

    assert assembled.tool_version == __version__
    assert assembled.provenance["tool_version"] != assembled.tool_version


@pytest.mark.parametrize("fixture", ["clean", "disclosures"])
def test_the_provenance_is_carried_whole(fixture: str) -> None:
    assembled = _report(fixture)

    assert assembled.provenance == run.read(RUNS / fixture).provenance


def test_the_normalizer_identity_strings_are_report_side() -> None:
    # `run.json` is written by `transcribe`, before any Text Normalization has happened, so these
    # cannot come from the Run (ADR-0020 redirecting ADR-0019's hand-off).
    tier_a, tier_b = report.normalizers()

    assert (tier_a, tier_b) == ("sdw-tier-a/1", "whisper-english/b80bcf6")
