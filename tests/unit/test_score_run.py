"""Reading a Run directory: the per-line schema, the sentinel, and the one integrity check.

Unit-level counterparts to the abort table's end-to-end rows (`tests/e2e/test_aborts.py`), where
the same two refusals are asserted through `main(argv)` with a non-zero exit.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sdw.errors import HardError
from sdw.score import run

RUNS = Path(__file__).parents[1] / "fixtures" / "runs"


def _copy(fixture: str, destination: Path) -> Path:
    shutil.copytree(RUNS / fixture, destination)
    return destination


def test_the_record_parses_into_adr_0019s_fields() -> None:
    record = run.read(RUNS / "clean").record

    assert [sample.id for sample in record] == [
        "rec_1a2b3c4d5e6f7081",
        "rec_3c4d5e6f70819a2b",
        "rec_5e6f70819a2b3c4d",
        "rec_70819a2b3c4d5e6f",
    ]
    first = record[0]
    assert first.reference == "The quick brown fox."
    assert first.hypothesis == "the quick brown fox"
    assert (first.error, first.split, first.speaker_id) == (None, "train", "spk_a")
    assert (first.duration, first.long_form) == (3.214, False)


def test_lines_are_read_in_file_order() -> None:
    # Append order *is* final order (ADR-0019), so the reader must not sort: a Record whose lines
    # are out of order is a fact about the file, not something to tidy away on read.
    ids = [sample.id for sample in run.read(RUNS / "clean").record]
    assert ids == sorted(ids)


def test_a_failed_line_is_null_hypothesis_and_keeps_every_other_field() -> None:
    # `""` is the model's output and `null` is the absence of one (ADR-0017/ADR-0019), and a failed
    # line carries its attributes so the Report can say *which* groups lost Samples.
    record = run.read(RUNS / "disclosures").record
    failed = next(sample for sample in record if sample.failed)
    empty = next(sample for sample in record if sample.hypothesis == "")

    assert (failed.hypothesis, failed.error) == (None, "decode_failed")
    assert (failed.session_id, failed.device) == ("2026-07-20-lounge", "iphone-15")
    assert not empty.failed


def test_the_provenance_is_kept_verbatim() -> None:
    # Not projected onto a type: ADR-0024 echoes the file whole into the JSON rendering, and a
    # projection would be a second relevance decision that drifts from ADR-0020's tier table.
    provenance = run.read(RUNS / "clean").provenance
    assert list(provenance) == [
        "record_version",
        "record_line_count",
        "tool_version",
        "dataset",
        "model",
        "decode",
        "language",
        "runtime",
        "host",
        "timing",
    ]


def test_a_run_without_the_sentinel_is_an_incomplete_run(tmp_path: Path) -> None:
    crashed = _copy("clean", tmp_path / "crashed")
    (crashed / run.PROVENANCE_FILENAME).unlink()

    with pytest.raises(HardError, match="incomplete Run"):
        run.read(crashed)


def test_a_record_disagreeing_with_its_line_count_is_truncated(tmp_path: Path) -> None:
    # The only integrity check there is (ADR-0019).
    truncated = _copy("clean", tmp_path / "truncated")
    record = truncated / run.RECORD_FILENAME
    kept = record.read_text(encoding="utf-8").splitlines(keepends=True)[:-1]
    record.write_text("".join(kept), encoding="utf-8")

    with pytest.raises(HardError, match="truncated"):
        run.read(truncated)


def test_a_record_longer_than_its_line_count_is_refused_too(tmp_path: Path) -> None:
    grown = _copy("clean", tmp_path / "grown")
    record = grown / run.RECORD_FILENAME
    lines = record.read_text(encoding="utf-8").splitlines(keepends=True)
    record.write_text("".join([*lines, lines[-1]]), encoding="utf-8")

    with pytest.raises(HardError, match="truncated"):
        run.read(grown)


def test_a_missing_run_directory_is_a_hard_error(tmp_path: Path) -> None:
    with pytest.raises(HardError, match="not a directory"):
        run.read(tmp_path / "nowhere")


def test_a_run_without_a_record_is_a_hard_error(tmp_path: Path) -> None:
    recordless = _copy("clean", tmp_path / "recordless")
    (recordless / run.RECORD_FILENAME).unlink()

    with pytest.raises(HardError, match="no Hypothesis Record"):
        run.read(recordless)


@pytest.mark.parametrize(
    ("line", "fragment"),
    [
        pytest.param("{not json}", "cannot parse", id="not-json"),
        pytest.param("[]", "expected a JSON object", id="not-an-object"),
        pytest.param('{"reference":"a"}', "id is missing", id="missing-id"),
        pytest.param('{"id":"rec_0","reference":"a","hypothesis":1}', "hypothesis", id="bad-type"),
        pytest.param(
            '{"id":"rec_0","reference":"a","hypothesis":"b","error":null,"split":"train",'
            '"session_id":"s","speaker_id":"p","prompt_id":"q","device":"d","environment":"e",'
            '"duration":"3.2","long_form":false}',
            "duration",
            id="duration-not-a-number",
        ),
        pytest.param(
            '{"id":"rec_0","reference":"a","hypothesis":"b","error":null,"split":"train",'
            '"session_id":"s","speaker_id":"p","prompt_id":"q","device":"d","environment":"e",'
            '"duration":3.2,"long_form":"yes"}',
            "long_form",
            id="long-form-not-a-boolean",
        ),
    ],
)
def test_a_record_that_will_not_parse_is_a_hard_error(
    tmp_path: Path, line: str, fragment: str
) -> None:
    # ADR-0017 lists "the Record will not parse" among `score`'s few hard errors. It is not an
    # integrity check — it is the reader refusing to guess at a schema ADR-0019 froze.
    broken = _copy("clean", tmp_path / "broken")
    (broken / run.RECORD_FILENAME).write_text(f"{line}\n", encoding="utf-8")

    with pytest.raises(HardError, match=fragment):
        run.read(broken)


@pytest.mark.parametrize(
    ("provenance", "fragment"),
    [
        pytest.param("{not json}", "cannot parse", id="not-json"),
        pytest.param("[]", "expected a JSON object", id="not-an-object"),
        pytest.param('{"record_version":"1"}', "record_line_count", id="no-line-count"),
        pytest.param('{"record_line_count":"4"}', "record_line_count", id="line-count-not-int"),
    ],
)
def test_provenance_that_will_not_parse_is_a_hard_error(
    tmp_path: Path, provenance: str, fragment: str
) -> None:
    broken = _copy("clean", tmp_path / "broken")
    (broken / run.PROVENANCE_FILENAME).write_text(provenance, encoding="utf-8")

    with pytest.raises(HardError, match=fragment):
        run.read(broken)
