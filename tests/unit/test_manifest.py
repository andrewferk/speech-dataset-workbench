"""The Manifest rows and the HF view: key order, field values, and the two views' parity (#28).

This is the deliverable, so these tests are what stands between a consumer and a dataset that
needs glue. They pin the four things a consumer's loader actually depends on: the fixed key order,
the exact per-field values, the mechanical HF transform, and byte-level determinism.

`build_dataset` is pure, so all of it is asserted with no tmpdir — the files are text in a dict,
not paths on disk (ADR-0008).
"""

import json
from typing import Any

from sdw.config import Config, ManifestConfig, QualityConfig, SplitConfig
from sdw.ingest import Recording
from sdw.manifest import Dataset, Sample, audio_path, build_dataset
from sdw.split import SPLIT_ORDER, split_sessions

# ADR-0006's table, verbatim and in order. Hard-coded rather than derived from `Sample` so the
# test would fail if a field were renamed, reordered, added, or dropped — deriving it would make
# the assertion tautological, and this order is a published contract.
CANONICAL_KEYS = [
    "id",
    "audio_filepath",
    "duration",
    "text",
    "perceived_text",
    "prompt_id",
    "speaker_id",
    "session_id",
    "device",
    "environment",
    "sample_rate",
    "num_channels",
    "content_hash",
    "lang",
    "split",
]


def _config(lang: str | None = None) -> Config:
    return Config(manifest=ManifestConfig(lang=lang), quality=QualityConfig(), split=SplitConfig())


def _recording(session_id: str, index: int, prompt_text: str = "Hello there.") -> Recording:
    """One Recording with plausible ids; ``index`` makes it distinct within its Session."""
    stem = f"{session_id}{index}"
    return Recording(
        recording_id=f"rec_{stem:>016}",
        content_hash=f"sha256:{stem:>064}",
        prompt_id=f"prm_{stem:>016}",
        path=f"{session_id}/{index}.wav",
        speaker_id="spk_01",
        session_id=session_id,
        prompt_text=prompt_text,
        device="Yeti",
        environment="quiet room",
    )


def _recordings(sizes: dict[str, int]) -> list[Recording]:
    return [
        _recording(session_id, index)
        for session_id, count in sizes.items()
        for index in range(count)
    ]


def _three_sessions() -> list[Recording]:
    """The default fixture: three Sessions, two Recordings each — enough to fill all three Splits.

    Named so that a test passing its own sizes — `TestFiles`' single Session, say — is visibly
    making a point about size rather than restating boilerplate.
    """
    return _recordings({"sess_01": 2, "sess_02": 2, "sess_03": 2})


def _durations(recordings: list[Recording], seconds: float = 1.5) -> dict[str, float]:
    return {recording.recording_id: seconds for recording in recordings}


def _build(
    recordings: list[Recording],
    durations: dict[str, float] | None = None,
    lang: str | None = None,
) -> Dataset:
    config = _config(lang)
    result = split_sessions(recordings, config.split)
    return build_dataset(recordings, result, durations or _durations(recordings), config)


def _lines(text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text.splitlines()]


def _all_lines(dataset: Dataset) -> list[dict[str, Any]]:
    return [row for name in SPLIT_ORDER for row in _lines(dataset.files[f"{name}.jsonl"])]


class TestCanonicalRow:
    """The per-Sample line NeMo reads with zero transformation."""

    def test_keys_are_the_adr_s_order_exactly(self) -> None:
        dataset = _build(_recordings({"sess_01": 3, "sess_02": 3, "sess_03": 3}))

        for row in _all_lines(dataset):
            assert list(row) == CANONICAL_KEYS

    def test_fields_carry_the_recording_s_values(self) -> None:
        recordings = [_recording("sess_01", 0)]
        recording = recordings[0]

        dataset = _build(recordings, {recording.recording_id: 2.0})
        (row,) = _all_lines(dataset)

        assert row["id"] == recording.recording_id
        assert row["text"] == recording.prompt_text
        assert row["prompt_id"] == recording.prompt_id
        assert row["speaker_id"] == recording.speaker_id
        assert row["session_id"] == recording.session_id
        assert row["device"] == recording.device
        assert row["environment"] == recording.environment
        assert row["content_hash"] == recording.content_hash

    def test_the_normalization_target_is_stamped_on_every_row(self) -> None:
        dataset = _build(_three_sessions())

        for row in _all_lines(dataset):
            assert row["sample_rate"] == 16000
            assert row["num_channels"] == 1

    def test_perceived_text_is_always_null(self) -> None:
        dataset = _build(_three_sessions())

        for row in _all_lines(dataset):
            assert row["perceived_text"] is None

    def test_text_is_verbatim_and_not_normalized_like_prompt_id(self) -> None:
        """`prompt_id`'s NFC/trim/collapse defines Prompt sameness, never the transcript."""
        recordings = [_recording("sess_01", 0, prompt_text="  Hello,   THERE.  ")]

        dataset = _build(recordings)
        (row,) = _all_lines(dataset)

        assert row["text"] == "  Hello,   THERE.  "

    def test_duration_is_rounded_to_milliseconds(self) -> None:
        recordings = [_recording("sess_01", 0)]

        dataset = _build(recordings, {recordings[0].recording_id: 1.23456789})
        (row,) = _all_lines(dataset)

        assert row["duration"] == 1.235

    def test_split_is_present_as_provenance(self) -> None:
        dataset = _build(_three_sessions())

        for name in SPLIT_ORDER:
            for row in _lines(dataset.files[f"{name}.jsonl"]):
                assert row["split"] == name

    def test_lang_carries_the_configured_code(self) -> None:
        dataset = _build(_recordings({"sess_01": 1, "sess_02": 1, "sess_03": 1}), lang="en")

        for row in _all_lines(dataset):
            assert row["lang"] == "en"

    def test_lang_is_null_when_unconfigured(self) -> None:
        dataset = _build(_recordings({"sess_01": 1, "sess_02": 1, "sess_03": 1}))

        for row in _all_lines(dataset):
            assert row["lang"] is None

    def test_no_quality_field_reaches_the_manifest(self) -> None:
        """The consumer's dataset is not entangled with the operator's diagnostics (#28)."""
        dataset = _build(_three_sessions())

        for row in _all_lines(dataset):
            assert not [key for key in row if "flag" in key or "clip" in key or "rms" in key]


class TestAudioPath:
    """`audio_filepath` is the one place the on-disk layout is spelled."""

    def test_is_relative_posix_bucketed_by_split(self) -> None:
        dataset = _build(_three_sessions())

        for name in SPLIT_ORDER:
            for row in _lines(dataset.files[f"{name}.jsonl"]):
                assert row["audio_filepath"] == f"audio/{name}/{row['id']}.wav"

    def test_the_helper_and_the_row_agree(self) -> None:
        """The stage that writes the WAV uses `audio_path`; the row must point at the same file."""
        dataset = _build(_three_sessions())

        for sample in dataset.samples:
            assert sample.audio_filepath == audio_path(sample.split, sample.id)


class TestHuggingFaceView:
    """`audio/<split>/metadata.jsonl` — the canonical row, two mechanical transforms."""

    def test_path_becomes_a_bare_file_name_in_place(self) -> None:
        dataset = _build(_three_sessions())

        rows = _lines(dataset.files["audio/train/metadata.jsonl"])
        assert [list(row)[:2] for row in rows] == [["id", "file_name"]] * len(rows)
        for row in rows:
            assert row["file_name"] == f"{row['id']}.wav"

    def test_split_is_dropped_because_the_folder_is_the_split(self) -> None:
        dataset = _build(_three_sessions())

        for row in _lines(dataset.files["audio/train/metadata.jsonl"]):
            assert "split" not in row
            assert "audio_filepath" not in row

    def test_every_other_field_is_at_parity_with_the_canonical_row(self) -> None:
        dataset = _build(_three_sessions(), lang="en")

        for name in SPLIT_ORDER:
            canonical = _lines(dataset.files[f"{name}.jsonl"])
            hf = _lines(dataset.files[f"audio/{name}/metadata.jsonl"])
            assert len(hf) == len(canonical)
            for canonical_row, hf_row in zip(canonical, hf, strict=True):
                dropped = ("audio_filepath", "split")
                shared = {k: v for k, v in canonical_row.items() if k not in dropped}
                assert {k: v for k, v in hf_row.items() if k != "file_name"} == shared

    def test_val_is_not_renamed(self) -> None:
        """HF reads `val` as a validation split already, so ADR-0003's folder name stands."""
        dataset = _build(_three_sessions())

        assert "audio/val/metadata.jsonl" in dataset.files
        assert not [path for path in dataset.files if "validation" in path]


class TestFiles:
    """Which files a build emits, and which it does not."""

    def test_all_three_canonical_manifests_are_always_emitted(self) -> None:
        """A Dataset too small to fill test still gives a consumer a readable, empty test.jsonl."""
        dataset = _build(_recordings({"sess_01": 2}))

        for name in SPLIT_ORDER:
            assert f"{name}.jsonl" in dataset.files
        assert dataset.files["test.jsonl"] == ""

    def test_no_hf_view_for_a_split_with_no_audio(self) -> None:
        dataset = _build(_recordings({"sess_01": 2}))

        assert "audio/train/metadata.jsonl" in dataset.files
        assert "audio/test/metadata.jsonl" not in dataset.files

    def test_kept_recordings_map_one_to_one_to_samples(self) -> None:
        recordings = _recordings({"sess_01": 4, "sess_02": 3, "sess_03": 2})

        dataset = _build(recordings)

        assert len(dataset.samples) == len(recordings)
        assert {s.id for s in dataset.samples} == {r.recording_id for r in recordings}
        assert len(_all_lines(dataset)) == len(recordings)


class TestDeterminism:
    """Byte-identical artifacts for the same input — what `dataset_version` rests on (#29)."""

    def test_reordering_recordings_csv_changes_no_byte(self) -> None:
        recordings = _recordings({"sess_01": 3, "sess_02": 3, "sess_03": 3})

        first = _build(recordings)
        second = _build(list(reversed(recordings)))

        assert first.files == second.files

    def test_rows_are_in_a_total_order_within_each_split(self) -> None:
        dataset = _build(_recordings({"sess_01": 3, "sess_02": 3, "sess_03": 3}))

        for name in SPLIT_ORDER:
            ids = [row["id"] for row in _lines(dataset.files[f"{name}.jsonl"])]
            assert ids == sorted(ids)

    def test_lines_are_lf_terminated_with_no_trailing_whitespace(self) -> None:
        dataset = _build(_three_sessions())

        for text in dataset.files.values():
            assert "\r" not in text
            assert text == "" or text.endswith("\n")
            for line in text.splitlines():
                assert line == line.strip()

    def test_separators_are_compact_and_utf_8_is_not_escaped(self) -> None:
        recordings = [_recording("sess_01", 0, prompt_text="Café ☕")]

        dataset = _build(recordings)
        text = dataset.files["train.jsonl"]

        assert "Café ☕" in text
        assert '", "' not in text
        assert '": ' not in text


class TestSampleShape:
    """The dataclass is the key order, so its field order is itself the contract."""

    def test_field_order_is_the_emitted_key_order(self) -> None:
        assert [f for f in Sample.__dataclass_fields__] == CANONICAL_KEYS
