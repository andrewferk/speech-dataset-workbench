"""Reading a Dataset Version as a stranger: the canonical JSONL and the descriptor (#164).

The contract half of this — that a real build parses — is asserted against an actual `build` in
`tests/e2e/test_transcribe.py` and `test_transcribe_preflight.py`. What is here is the *reading
rules*: where `lang` comes from, which files are read, and which are pointedly not.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdw.errors import HardError
from sdw.transcribe import dataset

_LINE = {
    "id": "rec_1a2b3c4d5e6f7081",
    "audio_filepath": "audio/train/rec_1a2b3c4d5e6f7081.wav",
    "duration": 3.214,
    "text": "The quick brown fox.",
    "perceived_text": None,
    "prompt_id": "prm_9f8e7d6c5b4a3021",
    "speaker_id": "spk_a",
    "session_id": "sess_a1",
    "device": "iphone-15",
    "environment": "quiet-room",
    "sample_rate": 16000,
    "num_channels": 1,
    "content_hash": "sha256:" + "0" * 64,
    "lang": None,
    "split": "train",
}


def _write(
    root: Path, *, lang: str | None = None, lines: dict[str, list[dict[str, object]]]
) -> Path:
    """A minimal built-shaped tree: three Manifests and a descriptor, no audio."""
    root.mkdir(parents=True, exist_ok=True)
    for name in dataset.MANIFEST_NAMES:
        split = name.removesuffix(".jsonl")
        body = "".join(json.dumps(line) + "\n" for line in lines.get(split, []))
        (root / name).write_text(body, encoding="utf-8")
    (root / dataset.DESCRIPTOR_NAME).write_text(
        json.dumps(
            {
                "manifest_version": "0.1",
                "tool_version": "0.1.0",
                "dataset_version": "sha256:" + "b" * 64,
                "config": {"manifest": {"lang": lang}},
            }
        ),
        encoding="utf-8",
    )
    return root


class TestDescriptor:
    """`dataset.json` — the three version strings and the Run's language input (ADR-0020)."""

    def test_lang_is_read_from_the_effective_config(self, tmp_path: Path) -> None:
        # `[manifest].lang`, where ADR-0016 points — not off a Manifest line, where the same fact
        # appears once per Sample and could disagree with itself.
        assert dataset.read_descriptor(_write(tmp_path, lang="de", lines={})).lang == "de"

    def test_an_absent_lang_is_none_rather_than_a_default(self, tmp_path: Path) -> None:
        # Defaulting is the Run's decision and is disclosed there; the reader reports what it read.
        assert dataset.read_descriptor(_write(tmp_path, lines={})).lang is None

    def test_a_descriptor_that_is_not_an_object_aborts(self, tmp_path: Path) -> None:
        root = _write(tmp_path, lines={})
        (root / dataset.DESCRIPTOR_NAME).write_text("[]", encoding="utf-8")
        with pytest.raises(HardError, match="not a JSON object"):
            dataset.read_descriptor(root)

    def test_a_non_string_lang_aborts(self, tmp_path: Path) -> None:
        root = _write(tmp_path, lines={})
        (root / dataset.DESCRIPTOR_NAME).write_text(
            json.dumps({"config": {"manifest": {"lang": 7}}}), encoding="utf-8"
        )
        with pytest.raises(HardError, match="non-string config.manifest.lang"):
            dataset.read_descriptor(root)

    def test_a_missing_version_string_aborts(self, tmp_path: Path) -> None:
        root = _write(tmp_path, lines={})
        (root / dataset.DESCRIPTOR_NAME).write_text('{"tool_version":"0.1.0"}', encoding="utf-8")
        with pytest.raises(HardError, match="dataset_version"):
            dataset.read_descriptor(root)


class TestSamples:
    """The canonical per-Split JSONL, merged into one total order over `id` (ADR-0019)."""

    def test_the_three_manifests_merge_into_one_id_order(self, tmp_path: Path) -> None:
        # Not grouped by Split: a single total order means nothing here needs a Split order at all,
        # which is what keeps `SPLIT_ORDER` off the critical path (ADR-0017/ADR-0019).
        root = _write(
            tmp_path,
            lines={
                "train": [{**_LINE, "id": "rec_c", "split": "train"}],
                "val": [{**_LINE, "id": "rec_a", "split": "val"}],
                "test": [{**_LINE, "id": "rec_b", "split": "test"}],
            },
        )
        assert [s.id for s in dataset.read_samples(root)] == ["rec_a", "rec_b", "rec_c"]

    def test_the_reference_is_v0_1_text_and_the_duration_is_verbatim(self, tmp_path: Path) -> None:
        (sample,) = dataset.read_samples(_write(tmp_path, lines={"train": [_LINE]}))
        assert sample.reference == _LINE["text"]
        assert sample.duration == _LINE["duration"]
        assert sample.audio_filepath == _LINE["audio_filepath"]

    def test_the_hugging_face_view_is_never_read(self, tmp_path: Path) -> None:
        # `audio/<split>/metadata.jsonl` exists and would half-work, which is why the choice is on
        # the record (ADR-0017). Broken here, and the read must not notice.
        root = _write(tmp_path, lines={"train": [_LINE]})
        hf = root / "audio" / "train"
        hf.mkdir(parents=True)
        (hf / "metadata.jsonl").write_text("{not json\n", encoding="utf-8")
        assert len(dataset.read_samples(root)) == 1

    def test_a_manifest_line_that_is_not_an_object_aborts(self, tmp_path: Path) -> None:
        root = _write(tmp_path, lines={})
        (root / "train.jsonl").write_text('["rec_a"]\n', encoding="utf-8")
        with pytest.raises(HardError, match="not a JSON object"):
            dataset.read_samples(root)

    def test_a_non_numeric_duration_aborts(self, tmp_path: Path) -> None:
        root = _write(tmp_path, lines={"train": [{**_LINE, "duration": "3.2"}]})
        with pytest.raises(HardError, match="duration"):
            dataset.read_samples(root)
