"""`sdw score` end to end: the Report header, both renderings, and the read-only contract.

A captured stream is only well defined through the CLI (ADR-0025), so these run `main(argv)` and
read stdout. They are **named assertions rather than goldens**: the Report is a header and nothing
else until the Metrics land, and a golden of a half-built artifact says "line 7 differs" where these
say which claim broke (ADR-0012's rule, applied to a Report that is not yet complete). ADR-0025's
captured-stream goldens arrive with the numbers they exist to pin.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from sdw.cli import main
from sdw.score.report import COMPARABILITY_NOTE, REFERENCE_NOTE

RUNS = Path(__file__).parents[1] / "fixtures" / "runs"
CLEAN = RUNS / "clean"
DISCLOSURES = RUNS / "disclosures"


def _score(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    assert main(["score", *argv]) == 0
    return capsys.readouterr().out


def _digest(capsys: pytest.CaptureFixture[str], directory: Path, *argv: str) -> str:
    return _score(capsys, "--run", str(directory), *argv)


def _document(capsys: pytest.CaptureFixture[str], directory: Path, *argv: str) -> dict[str, object]:
    parsed = json.loads(_score(capsys, "--run", str(directory), "--format", "json", *argv))
    assert isinstance(parsed, dict)
    return parsed


def _order(digest: str, *fragments: str) -> list[int]:
    positions = [digest.find(fragment) for fragment in fragments]
    assert -1 not in positions, f"missing from the Report: {fragments[positions.index(-1)]}"
    return positions


def test_the_five_header_items_print_in_adr_0022s_order(
    capsys: pytest.CaptureFixture[str],
) -> None:
    digest = _digest(capsys, CLEAN)

    positions = _order(
        digest,
        "Scope",
        "scored",
        REFERENCE_NOTE.split(" — ")[0],
        COMPARABILITY_NOTE.split(";")[0],
        "sdw-tier-a/1",
    )
    assert positions == sorted(positions)


def test_the_n_of_m_disclosure_prints_even_when_n_equals_m(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The one place the policy must be loud: a Report that scored a subset can never be mistaken
    # for one that scored everything, so the line is unconditional (ADR-0017/ADR-0022).
    assert "4 of 4 scored — 0 Transcription failure(s), 0 long_form" in _digest(capsys, CLEAN)


def test_failures_and_over_length_samples_are_counted_beside_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert "2 of 3 scored — 1 Transcription failure(s), 1 long_form" in _digest(capsys, DISCLOSURES)


def test_the_scope_label_follows_split(capsys: pytest.CaptureFixture[str]) -> None:
    assert "Scope        test\n" in _digest(capsys, CLEAN, "--split", "test")
    assert "1 of 1 scored" in _digest(capsys, CLEAN, "--split", "test")


def test_the_scoring_tool_version_is_attributed(capsys: pytest.CaptureFixture[str]) -> None:
    from sdw import __version__

    assert f"scored by sdw {__version__}" in _digest(capsys, CLEAN)


def test_the_digest_carries_the_provenance_under_adr_0020s_tier_names(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Without it, `diff` of two Reports renders clean between a `whisper-tiny` Run and a
    # `whisper-large-v3-turbo` Run while naming neither model (ADR-0024).
    digest = _digest(capsys, CLEAN)

    positions = _order(
        digest,
        "Transcription conditions — must match to compare",
        "openai/whisper-large-v3-turbo @ 41f01f3fe87f28c78e2fbf8b568835947dd65ed9 (mit)",
        "Dataset — must match, or escalate to a masked diff of the two Records",
        "sha256:9f2ac418",
        "Disclosed — may differ; the same question under different arithmetic",
        "transcribed 0.2.0",
    )
    assert positions == sorted(positions)


def test_the_digest_omits_the_never_relevant_tier(capsys: pytest.CaptureFixture[str]) -> None:
    # `timing` and `record_version` are ADR-0020's *never relevant* tier and `record_line_count` is
    # discharged as N-of-M; all three ride along in the JSON echo instead (ADR-0024).
    digest = _digest(capsys, CLEAN)

    assert "2026-08-03T14:02:11Z" not in digest
    assert "record_line_count" not in digest


def test_the_json_rendering_echoes_run_json_verbatim(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Verbatim, so ADR-0020's tier table applies to the Report without translation and a diff
    # scoped to that key *is* the tier check (ADR-0024). A curated subset would drift from the file.
    document = _document(capsys, CLEAN)

    assert document["run"] == json.loads((CLEAN / "run.json").read_text(encoding="utf-8"))


def test_the_json_rendering_carries_the_same_report_as_the_digest(
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = _document(capsys, DISCLOSURES, "--split", "train")

    assert document["scope"] == {"split": "train", "splits_present": ["train", "test"]}
    assert document["samples"] == {"in_scope": 2, "scored": 1, "failed": 1, "long_form": 1}
    assert document["normalizers"] == {
        "tier_a": "sdw-tier-a/1",
        "tier_b": "whisper-english/b80bcf6",
    }
    assert document["disclosures"] == {
        "reference": REFERENCE_NOTE,
        "comparability": COMPARABILITY_NOTE,
    }


def test_the_json_rendering_is_one_document_with_a_fixed_key_order(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # One object, not JSONL, and key order is declaration order rather than alphabetical
    # (ADR-0022), which is what keeps two Reports lining up under `diff`.
    raw = _score(capsys, "--run", str(CLEAN), "--format", "json")

    assert raw.endswith("}\n") and raw.count("\n") == 1
    assert list(json.loads(raw)) == [
        "scope",
        "samples",
        "disclosures",
        "normalizers",
        "tool_version",
        "run",
    ]


def test_the_default_format_is_text(capsys: pytest.CaptureFixture[str]) -> None:
    assert _digest(capsys, CLEAN) == _digest(capsys, CLEAN, "--format", "text")


@pytest.mark.parametrize("fmt", ["text", "json"], ids=["text", "json"])
def test_score_writes_nothing_anywhere(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fmt: str
) -> None:
    # `score` is not merely pure, it is **read-only** (ADR-0021): a Run's bytes are fixed at the end
    # of Transcription and never change again, which is what lets ADR-0020's masked-diff escalation
    # be stated without a "did someone score into this?" caveat.
    directory = tmp_path / "run"
    shutil.copytree(CLEAN, directory)
    before = {path.name: path.read_bytes() for path in sorted(directory.iterdir())}

    assert main(["score", "--run", str(directory), "--format", fmt]) == 0
    capsys.readouterr()

    assert {path.name: path.read_bytes() for path in sorted(directory.iterdir())} == before


def test_the_report_is_byte_identical_across_invocations(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A pure function of the Run, the Scope and the tool — no wall-clock, no host fact of the
    # scoring machine, nothing observed (ADR-0022 as narrowed by ADR-0024).
    assert _digest(capsys, CLEAN) == _digest(capsys, CLEAN)


def test_score_takes_no_dataset_argument_and_no_config(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Purity is a property of the command surface: there is no dataset argument to pass, so there
    # is no way to make Scoring impure by accident (ADR-0017/ADR-0018).
    with pytest.raises(SystemExit) as exc:
        main(["score", "--help"])
    assert exc.value.code == 0

    usage = capsys.readouterr().out
    assert "--config" not in usage
    assert "--dataset" not in usage and "--data-in" not in usage
