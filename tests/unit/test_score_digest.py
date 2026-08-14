"""The digest's fixed shape, how it spells a fact it quotes, and the rules its body follows.

The shape is invariant (ADR-0022): every row prints at every value, so a diff between two Reports
shows a value changing rather than a line appearing. That has to hold for a `run.json` missing a
block too — the header is not allowed to shrink around a Run whose provenance is thin, because a
shrinking header is exactly the diff that reads as "nothing changed."

The goldens in `tests/e2e/test_score_goldens.py` pin the bytes; these name the claims, so a break
says *which rule* moved rather than which line number differs (ADR-0012).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sdw.score import digest, report, run
from sdw.score.aggregate import ScoredSample, aggregate, scored
from sdw.score.report import Report
from sdw.score.text_normalization import TIER_A

RUNS = Path(__file__).parents[1] / "fixtures" / "runs"

_ROWS = ("model", "decode", "language", "dataset_version", "runtime", "host", "tool")

_PROVENANCE_HEADING = "Transcription conditions — must match to compare"


def _sample(
    reference: str = "one two three four", hypothesis: str = "one two three five", **fields: str
) -> ScoredSample:
    return scored(
        id=fields.get("id", "rec_0000000000000001"),
        reference=reference,
        hypothesis=hypothesis,
        split=fields.get("split", "train"),
        session_id=fields.get("session_id", "sess-1"),
        prompt_id=fields.get("prompt_id", "p-1"),
        device=fields.get("device", "mic-a"),
        environment=fields.get("environment", "room-a"),
    )


def _report(provenance: dict[str, Any], *samples: ScoredSample) -> Report:
    scope = samples or (_sample(),)
    return Report(
        splits=("train",),
        selected_split=None,
        in_scope=len(scope),
        scored=len(scope),
        failed=0,
        long_form=0,
        provenance=provenance,
        tool_version="0.2.0",
        samples=scope,
        aggregation=aggregate(scope),
    )


def _rendered(fixture: str, split: str | None = None) -> str:
    return digest.render(report.assemble(run.read(RUNS / fixture), split=split))


def _section(rendered: str, heading: str) -> list[str]:
    """One blank-line-delimited section, by the line it starts with — sections are the unit."""
    lines = rendered.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith(heading))
    end = next((index for index in range(start, len(lines)) if not lines[index]), len(lines))
    return lines[start:end]


def _rows(rendered: str) -> dict[str, str]:
    """The provenance rows as ``label -> value``; other sections indent by two as well."""
    section = _section(rendered, _PROVENANCE_HEADING)
    matches = (re.match(r"^ {2}(\S+) +(.*)$", line) for line in section)
    return {match[1]: match[2] for match in matches if match}


# --- The header and the provenance it quotes ------------------------------------------------------


def test_every_provenance_row_prints_even_when_the_file_carries_none_of_them() -> None:
    rows = _rows(digest.render(_report({"record_line_count": 1})))

    assert list(rows) == list(_ROWS)
    assert [rows[row] for row in _ROWS[:-1]] == [digest.ABSENT] * (len(_ROWS) - 1)
    assert rows["tool"] == f"transcribed {digest.ABSENT}"


def test_a_partially_present_block_prints_the_facts_it_has() -> None:
    rendered = digest.render(_report({"model": {"repo_id": "openai/whisper-tiny"}}))

    assert f"openai/whisper-tiny @ {digest.ABSENT} ({digest.ABSENT})" in rendered


def test_json_scalars_are_spelled_as_the_file_spells_them() -> None:
    # `null` and `false`, never `None` and `False`: the digest quotes `run.json`, and a reader
    # comparing a Report against the file should not have to translate.
    rendered = digest.render(
        _report({"decode": {"temperature": None, "do_sample": False, "num_beams": 1}})
    )

    assert "task" not in rendered
    assert "temperature=null · do_sample=false · num_beams=1" in rendered


def test_the_headers_five_items_print_for_a_run_with_no_provenance_at_all() -> None:
    rendered = digest.render(_report({}))

    assert "Scope        train (every Split present)" in rendered
    assert "1 of 1 scored — 0 Transcription failure(s), 0 long_form" in rendered
    assert "scored by sdw 0.2.0" in rendered


# --- The body: headline, table, delta, Breakdowns, worklist ---------------------------------------


def test_the_body_prints_adr_0022s_sections_in_its_order() -> None:
    rendered = _rendered("errors")

    positions = [
        rendered.index(fragment)
        for fragment in (
            "Headline",
            "Pooled over the Scope",
            "Tier B − Tier A delta",
            "Breakdown — split",
            "Breakdown — session",
            "Breakdown — prompt",
            "Breakdown — device",
            "Breakdown — environment",
            "Worklist",
        )
    ]

    assert positions == sorted(positions)


def test_the_headline_is_tier_a_pooled_wer_with_its_scope_attached() -> None:
    # Tier B is the aggressive normalizer; heading the Report with it would lower the number by
    # hiding disfluency, on exactly the population this product exists for (ADR-0018/ADR-0022).
    # `errors`: 3 + 2 + 1 + 1 errors over 1 + 2 + 4 + 4 Reference tokens = 7/11.
    assert "Headline  Tier A Pooled WER 63.64% over 4 scored Sample(s)" in _rendered("errors")


def test_the_six_numbers_print_under_both_tiers() -> None:
    table = _section(_rendered("single"), "Pooled over the Scope")

    assert table == [
        "Pooled over the Scope",
        "  Metric   Tier A   Tier B",
        "  WER      25.00%   25.00%",
        "  CER       5.00%    5.00%",
        "  SER     100.00%  100.00%",
    ]


def test_the_tier_difference_is_named_a_delta_and_never_a_deviation() -> None:
    # ADR-0018 names it a delta; "deviation" is the speaker's, and the two must not share a word.
    rendered = _rendered("normalization")
    section = _section(rendered, "Tier B − Tier A delta")

    assert "deviation" not in " ".join(section)
    # Tier A pools 3 word errors over 11 tokens (27.27%); Tier B, which spells `O'Brien` as
    # `0 brien`, pools 2 over 13 (15.38%) — the aggressive normalizer reads *better* by 11.89
    # points, which is the whole reason it is not the headline. Characters: 6/50 against 2/57.
    assert section[1:] == ["  WER  -11.89", "  CER   -8.49", "  SER   +0.00"]


def test_a_percentage_renders_at_two_fixed_decimal_places() -> None:
    # Fixed places, not `round`: `round` drops trailing zeros and leaves a ragged column where a
    # scannable one was wanted (ADR-0022, quoting v0.1's `_evidence`).
    rendered = _rendered("clean")

    assert "0.00%" in rendered
    assert re.search(r"\d+\.\d{3}%", rendered) is None
    assert re.search(r"\d+\.\d%", rendered) is None


def test_an_undefined_rate_prints_as_the_one_absent_spelling_never_as_zero() -> None:
    # `degenerate`'s `val` group holds only an empty-vs-empty Sample: WER and CER are undefined for
    # it and SER is a real 0.00%, which is ADR-0018's table rendered rather than restated.
    group = next(
        line for line in _section(_rendered("degenerate"), "Breakdown — split") if " val " in line
    )

    assert group.split() == [
        "val",
        "1",
        digest.ABSENT,
        digest.ABSENT,
        digest.ABSENT,
        digest.ABSENT,
        "0.00%",
        "0.00%",
    ]


def test_every_breakdown_carries_its_groups_size_and_the_macro_across_them() -> None:
    # Nothing is suppressed and no threshold exists: a group of one prints as a group of one, which
    # is what `n` is for (ADR-0022).
    section = _section(_rendered("degenerate"), "Breakdown — prompt")

    assert section[0] == "Breakdown — prompt, 4 group(s)"
    assert [line.split()[0] for line in section[-4:]] == ["macro", "macro", "macro", "groups"]
    # Two of the four Prompt groups normalize to an empty Reference, so the WER Macro excludes them
    # and says how many — the exclusion is per Metric, and SER excludes none.
    assert section[-1].split()[3:] == ["2", "3", "2", "3", "0", "0"]


def test_the_worklist_is_worst_first_with_ties_broken_by_id() -> None:
    listed = [
        line.split()[0]
        for line in _section(_rendered("errors"), "Worklist")[1:]
        if line.startswith("  rec_")
    ]

    # 300%, 100%, then the two Samples tied at 25% in `id` order — no top-N, so all four print.
    assert listed == [
        "rec_51aa62bb73cc84dd",
        "rec_52bb63cc74dd85ee",
        "rec_53cc64dd75ee86ff",
        "rec_54dd65ee76ff8700",
    ]


def test_a_sample_whose_wer_is_undefined_sorts_after_every_ranked_one() -> None:
    # An empty normalized Reference against a Hypothesis that inserted tokens has erred and cannot
    # be ranked against a rate, so it lands last rather than being given a number it does not have.
    listed = [
        line.split()[0]
        for line in _section(_rendered("degenerate"), "Worklist")
        if line.startswith("  rec_")
    ]

    assert listed == ["rec_44dd55ee66ff7700", "rec_42bb53cc64dd75ee"]


def test_an_empty_normalized_text_is_spelled_apart_from_an_undefined_rate() -> None:
    # Two encodings of *no value here* is how they come to disagree (ADR-0022): an empty normalized
    # text is a fact — the model said nothing, or a tier deleted everything — while `ABSENT` marks
    # a rate ADR-0018 leaves undefined. `disclosures`' empty Hypothesis shows both on one entry.
    worklist = _section(_rendered("disclosures"), "Worklist")

    assert worklist[-1] == f"    hyp                 {digest.EMPTY}"
    assert digest.EMPTY != digest.ABSENT


def test_a_percentage_is_the_rounded_rate_shifted_not_a_second_rounding() -> None:
    # ADR-0022: the percentage is a rendering of the same rate rounded at `RATIO_DP`, shifted by
    # the same two places — so the digest and the JSON document can never disagree about a value.
    assert digest.PERCENT_DP == digest.RATIO_DP - 2
    assert digest._percent(1 / 3) == f"{round(1 / 3, digest.RATIO_DP) * 100:.2f}%"


def test_clean_samples_are_counted_not_listed() -> None:
    # `render_digest`'s worklist rule, transferred without modification (ADR-0007/ADR-0022).
    worklist = _section(_rendered("clean"), "Worklist")

    assert worklist == [
        "Worklist — 0 of 4 scored Sample(s) erred under sdw-tier-a/1, worst first; "
        "4 clean, counted not listed"
    ]


def test_the_worklist_carries_the_counts_and_the_normalized_pair_behind_each_rate() -> None:
    # "3 substitutions" without the text is a number an operator cannot act on, and the normalized
    # text exists in no other artifact — the Record holds only the raw pair (ADR-0022/ADR-0026).
    worklist = _section(_rendered("single"), "Worklist")

    assert worklist[1:] == [
        "  rec_61aa72bb83cc94dd  WER 25.00% · CER 5.00% · words S=1 D=0 I=0 N=4 · "
        "chars S=0 D=0 I=1 N=20",
        "    ref                 only one sample here",
        "    hyp                 only one sample there",
    ]


def test_the_worklist_membership_rule_is_any_tier_a_error() -> None:
    erred = _sample(reference="one two", hypothesis="one three", id="rec_0000000000000002")
    clean = _sample(reference="one two", hypothesis="one two", id="rec_0000000000000003")

    worklist = _section(digest.render(_report({}, erred, clean)), "Worklist")

    assert worklist[0].startswith("Worklist — 1 of 2 scored Sample(s) erred under ")
    assert clean.metrics[TIER_A].sentence_error is False
    assert [line.split()[0] for line in worklist if line.startswith("  rec_")] == [erred.id]
