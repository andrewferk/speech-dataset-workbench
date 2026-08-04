"""The Record's per-line schema and its incremental writer (#164, ADR-0019).

The e2e golden pins these bytes against a real build; this module pins the two claims a golden
cannot state in the negative — that the key order is ADR-0019's list rather than whatever the
dataclass happens to hold, and that a line is on disk before the next Sample is attempted.
"""

from __future__ import annotations

import json
from pathlib import Path

from sdw.transcribe import record
from sdw.transcribe.dataset import Sample

# ADR-0019's table, spelled out. Written as a literal, not derived from the dataclass: a test that
# reads the code it checks agrees with itself.
KEY_ORDER = [
    "id",
    "reference",
    "hypothesis",
    "error",
    "split",
    "session_id",
    "speaker_id",
    "prompt_id",
    "device",
    "environment",
    "duration",
    "long_form",
]

SAMPLE = Sample(
    id="rec_1a2b3c4d5e6f7081",
    reference="The quick brown fox.",
    split="train",
    session_id="2026-07-14-quiet",
    speaker_id="spk_a",
    prompt_id="prm_9f8e7d6c5b4a3021",
    device="iphone-15",
    environment="quiet-room",
    duration=3.214,
    audio_filepath="audio/train/rec_1a2b3c4d5e6f7081.wav",
)


def _written(tmp_path: Path, *lines: record.RecordLine) -> list[dict[str, object]]:
    path = tmp_path / record.RECORD_NAME
    with record.RecordWriter(path) as writer:
        for line in lines:
            writer.append(line)
    return [json.loads(raw) for raw in path.read_text(encoding="utf-8").splitlines()]


def test_the_key_order_is_the_one_adr_0019_fixes(tmp_path: Path) -> None:
    line = _written(tmp_path, record.transcribed(SAMPLE, hypothesis="hi", long_form=False))[0]
    assert list(line) == KEY_ORDER


def test_a_hypothesis_is_null_only_when_transcription_failed(tmp_path: Path) -> None:
    transcribed, empty, failed = _written(
        tmp_path,
        record.transcribed(SAMPLE, hypothesis="hi", long_form=False),
        record.transcribed(SAMPLE, hypothesis="", long_form=False),
        record.failed(SAMPLE, long_form=False),
    )
    assert (transcribed["hypothesis"], transcribed["error"]) == ("hi", None)
    assert (empty["hypothesis"], empty["error"]) == ("", None)
    assert (failed["hypothesis"], failed["error"]) == (None, record.DECODE_FAILED)


def test_the_reference_carries_v0_1_text_verbatim(tmp_path: Path) -> None:
    # The role, not the dataset's word — `reference` beside `hypothesis` is the pair every scoring
    # library is written in (ADR-0015/ADR-0019).
    line = _written(tmp_path, record.transcribed(SAMPLE, hypothesis="", long_form=False))[0]
    assert line["reference"] == SAMPLE.reference
    assert line["duration"] == SAMPLE.duration


def test_each_line_is_on_disk_before_the_next_is_written(tmp_path: Path) -> None:
    # What makes a crashed Record a valid prefix rather than a lost buffer (ADR-0017/ADR-0019).
    path = tmp_path / record.RECORD_NAME
    with record.RecordWriter(path) as writer:
        writer.append(record.transcribed(SAMPLE, hypothesis="one", long_form=False))
        assert len(path.read_text(encoding="utf-8").splitlines()) == 1
        writer.append(record.transcribed(SAMPLE, hypothesis="two", long_form=True))
        assert writer.line_count == 2
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
