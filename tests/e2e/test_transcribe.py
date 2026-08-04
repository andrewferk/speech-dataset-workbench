"""One `transcribe` Run against a fake backend, from a real `build` (#164, ADR-0025).

The dataset under test is **built**, not hand-authored: the committed reference `--data-in` goes
through the existing pipeline into a tmpdir and `transcribe` reads the result. That is the only
arrangement in which the stranger-consumer claim is *tested* rather than asserted — a committed
Manifest fixture would be a second copy of the contract that goes stale silently, which is the exact
failure the dogfood exists to catch. A field drifting in `sdw.manifest` turns this suite red.

The model is a fake at ADR-0025's internal seam, so the whole write path runs in a venv with no ASR
extra. `hypotheses.jsonl` is pinned byte-for-byte against a committed golden — line order, key
order, the schema and the failure marker are four things a refactor can break without breaking
anything that reads them today. `run.json` is excluded from that golden and asserted field-wise: it
carries observed facts (wall clock, host) rather than read ones.

No assertion here is about *text*: the fixtures are synthesized tones, which contain no speech. The
claims stop at the seam — a `float32` array of the expected shape in, every Manifest line out as a
Record line — and that is a finding rather than a gap (ADR-0025).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from sdw.cli import main
from sdw.transcribe import pipeline, provenance, record
from sdw.transcribe.backend import BackendProvenance, Language
from tests import synth

REPO_ROOT = Path(__file__).parents[2]
GOLDEN = REPO_ROOT / "tests" / "fixtures" / "transcribe" / "golden" / record.RECORD_NAME

# One outcome per Sample, in transcription order — which ADR-0019 makes `id`-ascending order, so the
# golden pins the two together: the empty Hypothesis and the failure land on the ids they land on
# only if the Run processed the corpus in that order.
_OUTCOMES: tuple[str | None, ...] = (
    "the quick brown fox jumped over the lazy dog",
    # `""` is the model saying nothing — a different fact from a failure, and preserved as one.
    "",
    # `None` here means *raise*: a decode that blew up, with an absolute path in its message, which
    # must reach stderr and never the Record (ADR-0019).
    None,
    "a stitch in time saves nine",
)

# What the fake claims to be. Shaped like ADR-0020's blocks so the field-wise assertions below are
# about `run.json`'s structure rather than about the fake's imagination.
_MODEL = {"repo_id": "fake/model", "revision": "0" * 40, "license": "mit"}
_DECODE = {
    "task": "transcribe",
    "do_sample": False,
    "num_beams": 1,
    "temperature": None,
    "condition_on_prev_tokens": False,
    "return_timestamps": False,
}
_RUNTIME = {"name": "fake", "device": "cpu", "dtype": "float32"}


@dataclass
class FakeBackend:
    """A hand-written stand-in for the model — the seam's whole surface, and nothing else.

    It records what it was handed, so the tests can assert the two claims that survive having no
    speech: the array's dtype and shape, and the order the Samples arrived in.
    """

    calls: list[tuple[np.dtype[Any], tuple[int, ...], Language]] = field(default_factory=list)

    @property
    def provenance(self) -> BackendProvenance:
        return BackendProvenance(model=_MODEL, decode=_DECODE, runtime=_RUNTIME)

    def transcribe(self, waveform: npt.NDArray[np.float32], language: Language) -> str:
        outcome = _OUTCOMES[len(self.calls)]
        self.calls.append((waveform.dtype, waveform.shape, language))
        if outcome is None:
            raise RuntimeError(f"decode failed reading /private/var/tmp/{len(self.calls)}.wav")
        return outcome


def _built(root: Path) -> Path:
    """The committed reference `--data-in`, built into ``root`` — the dataset under test."""
    data_in = root / "in"
    synth.write_reference_tree(data_in)
    data_out = root / "dataset"
    assert main(["build", "--data-in", str(data_in), "--data-out", str(data_out)]) == 0
    return data_out


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def transcribed(tmp_path: Path) -> tuple[Path, FakeBackend, Path]:
    """One completed Run: the Run directory, the fake that produced it, and the dataset."""
    dataset = _built(tmp_path)
    backend = FakeBackend()
    run_dir = pipeline.run(dataset=dataset, eval_out=tmp_path / "eval", backend=backend)
    return run_dir, backend, dataset


class TestRecord:
    """`hypotheses.jsonl` — the durable format claim, pinned byte for byte."""

    def test_the_record_matches_the_committed_golden(
        self, transcribed: tuple[Path, FakeBackend, Path]
    ) -> None:
        run_dir, _, _ = transcribed
        assert (run_dir / record.RECORD_NAME).read_bytes() == GOLDEN.read_bytes()

    def test_samples_are_transcribed_in_id_order(
        self, transcribed: tuple[Path, FakeBackend, Path]
    ) -> None:
        # Append order *is* final order (ADR-0019), so the file's order is only trustworthy if the
        # backend saw the Samples in it — which the golden alone cannot show.
        run_dir, backend, _ = transcribed
        ids = [json.loads(line)["id"] for line in _record_lines(run_dir)]
        assert ids == sorted(ids)
        assert len(backend.calls) == len(ids)

    def test_the_backend_is_handed_a_float32_array(
        self, transcribed: tuple[Path, FakeBackend, Path]
    ) -> None:
        # The array, never a path: every path-based entry point routes through FFmpeg (ADR-0016).
        _, backend, _ = transcribed
        for dtype, shape, language in backend.calls:
            assert dtype == np.float32
            assert len(shape) == 1 and shape[0] > 0
            # The reference tree declares no `lang`, so v0.1's `null` defaults to `en` (ADR-0016).
            assert language == Language(value="en", source="defaulted")

    def test_a_failed_sample_is_a_present_line_carrying_every_field(
        self, transcribed: tuple[Path, FakeBackend, Path]
    ) -> None:
        run_dir, _, _ = transcribed
        lines = [json.loads(line) for line in _record_lines(run_dir)]
        failed = [line for line in lines if line["hypothesis"] is None]
        assert len(failed) == 1
        assert failed[0]["error"] == record.DECODE_FAILED
        assert failed[0]["session_id"] and failed[0]["device"] and failed[0]["reference"]

    def test_an_empty_hypothesis_stays_distinct_from_a_failure(
        self, transcribed: tuple[Path, FakeBackend, Path]
    ) -> None:
        run_dir, _, _ = transcribed
        lines = [json.loads(line) for line in _record_lines(run_dir)]
        empty = [line for line in lines if line["hypothesis"] == ""]
        assert len(empty) == 1
        assert empty[0]["error"] is None

    def test_no_exception_text_reaches_the_record(
        self, transcribed: tuple[Path, FakeBackend, Path]
    ) -> None:
        # `error` draws from a closed vocabulary precisely so an absolute path can never land in a
        # durable artifact and make two Records of the same corpus undiffable (ADR-0019).
        run_dir, _, _ = transcribed
        assert "/private/var" not in (run_dir / record.RECORD_NAME).read_text(encoding="utf-8")


class TestRunDescriptor:
    """`run.json` — written last, asserted field-wise rather than goldened (ADR-0025)."""

    def test_the_sentinel_counts_the_record_it_describes(
        self, transcribed: tuple[Path, FakeBackend, Path]
    ) -> None:
        run_dir, _, _ = transcribed
        document = _run_json(run_dir)
        assert document["record_line_count"] == len(_record_lines(run_dir))
        assert document["record_version"] == record.RECORD_VERSION

    def test_the_three_tool_versions_are_independent(
        self, transcribed: tuple[Path, FakeBackend, Path]
    ) -> None:
        # Built, transcribed, scored — and no two assumed equal. Top-level names the tool that wrote
        # *this* file; the scoring occurrence is Report-side and absent here (ADR-0020).
        run_dir, _, dataset = transcribed
        document = _run_json(run_dir)
        built = json.loads((dataset / "dataset.json").read_text(encoding="utf-8"))
        assert document["dataset"]["tool_version"] == built["tool_version"]
        assert document["dataset"]["dataset_version"] == built["dataset_version"]
        assert document["dataset"]["manifest_version"] == built["manifest_version"]
        assert isinstance(document["tool_version"], str)

    def test_the_nested_blocks_are_present_and_shaped(
        self, transcribed: tuple[Path, FakeBackend, Path]
    ) -> None:
        document = _run_json(transcribed[0])
        assert list(document) == [
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
        assert document["model"] == _MODEL
        assert document["decode"] == _DECODE
        assert document["language"] == {"value": "en", "source": "defaulted"}
        assert set(document["host"]) == {"platform_machine", "platform_system"}
        assert set(document["timing"]) == {"started_at", "finished_at"}

    def test_the_run_carries_no_identifier_and_no_integrity_hash(
        self, transcribed: tuple[Path, FakeBackend, Path]
    ) -> None:
        # A hash-shaped string in a file parallel to `dataset.json` *is* an identity to the next
        # reader, whatever key it sits under (ADR-0020).
        run_dir, _, _ = transcribed
        raw = (run_dir / provenance.RUN_DESCRIPTOR_NAME).read_text(encoding="utf-8")
        document = _run_json(run_dir)
        assert not [key for key in document if key.endswith("id") or key == "run"]
        assert "sha256:" not in raw.replace(document["dataset"]["dataset_version"], "")

    def test_no_normalizer_identity_appears(
        self, transcribed: tuple[Path, FakeBackend, Path]
    ) -> None:
        # Text Normalization happens in `score`, so naming a Normalizer here would describe an event
        # that had not happened when the file was written (ADR-0020).
        raw = (transcribed[0] / provenance.RUN_DESCRIPTOR_NAME).read_text(encoding="utf-8")
        assert "tier-a" not in raw and "whisper-english" not in raw

    def test_no_wall_clock_or_host_fact_reaches_the_record(
        self, transcribed: tuple[Path, FakeBackend, Path]
    ) -> None:
        # The boundary is the file, not a compromise: two Records of one Dataset Version diff to
        # model variance alone (ADR-0020).
        run_dir, _, _ = transcribed
        document = _run_json(run_dir)
        lines = (run_dir / record.RECORD_NAME).read_text(encoding="utf-8")
        for observed in (*document["host"].values(), *document["timing"].values()):
            assert observed not in lines


class TestRunDirectory:
    """Where a Run lands, what it is called, and what else `--eval-out` acquires (ADR-0021)."""

    def test_the_run_directory_is_named_from_the_start_timestamp(
        self, transcribed: tuple[Path, FakeBackend, Path]
    ) -> None:
        run_dir, _, _ = transcribed
        started = _run_json(run_dir)["timing"]["started_at"]
        assert run_dir.name == provenance.RUN_DIR_PREFIX + started.translate(
            str.maketrans("", "", "-:")
        )

    def test_eval_out_holds_run_directories_and_nothing_else(
        self, transcribed: tuple[Path, FakeBackend, Path]
    ) -> None:
        # No index, no marker, no `latest` — `ls <eval-out>` is the complete listing (ADR-0021).
        run_dir, _, _ = transcribed
        assert [entry.name for entry in run_dir.parent.iterdir()] == [run_dir.name]
        assert sorted(entry.name for entry in run_dir.iterdir()) == [
            record.RECORD_NAME,
            provenance.RUN_DESCRIPTOR_NAME,
        ]

    def test_no_staging_directory_is_used(
        self, transcribed: tuple[Path, FakeBackend, Path]
    ) -> None:
        run_dir, _, _ = transcribed
        assert not list(run_dir.parent.glob("*.tmp")) and not list(run_dir.parent.glob("*.old"))

    def test_the_run_path_is_printed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        dataset = _built(tmp_path)
        run_dir = pipeline.run(dataset=dataset, eval_out=tmp_path / "eval", backend=FakeBackend())
        assert capsys.readouterr().out.strip().splitlines()[-1] == str(run_dir)

    def test_nothing_is_written_into_the_dataset_directory(self, tmp_path: Path) -> None:
        dataset = _built(tmp_path)
        before = _tree_bytes(dataset)
        pipeline.run(dataset=dataset, eval_out=tmp_path / "eval", backend=FakeBackend())
        assert _tree_bytes(dataset) == before


class TestLongForm:
    """An over-length Sample: disclosed on the line and at Run level, never rejected (ADR-0016)."""

    def test_an_over_length_sample_is_recorded_and_counted(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Past Whisper's fixed 30 s window, and past ADR-0007's *configurable* 20 s soft flag — two
        # different facts, which is why `long_form` is not `duration_out_of_range` (ADR-0019).
        data_in = tmp_path / "in"
        data_in.mkdir()
        synth.write_wav(
            data_in / "long.wav",
            freq_hz=400.0,
            amp_dbfs=-18.0,
            duration_s=31.0,
            sample_rate=16000,
            bit_depth=16,
            channels=1,
        )
        synth.write_recordings_csv(data_in, [{"path": "long.wav"}])
        dataset = tmp_path / "dataset"
        assert main(["build", "--data-in", str(data_in), "--data-out", str(dataset)]) == 0
        capsys.readouterr()

        run_dir = pipeline.run(dataset=dataset, eval_out=tmp_path / "eval", backend=FakeBackend())

        assert json.loads(_record_lines(run_dir)[0])["long_form"] is True
        assert "long-form" in capsys.readouterr().err


class TestCrash:
    """An interrupted Run: a valid prefix, no sentinel, and nothing sweeps it (ADR-0019/0021)."""

    def test_an_interrupted_run_leaves_a_valid_prefix_and_no_sentinel(self, tmp_path: Path) -> None:
        dataset = _built(tmp_path)
        eval_out = tmp_path / "eval"
        with pytest.raises(KeyboardInterrupt):
            pipeline.run(dataset=dataset, eval_out=eval_out, backend=_Interrupted())
        (run_dir,) = list(eval_out.iterdir())
        assert not (run_dir / provenance.RUN_DESCRIPTOR_NAME).exists()
        lines = _record_lines(run_dir)
        assert len(lines) == 1
        assert json.loads(lines[0])["hypothesis"] == _OUTCOMES[0]


@dataclass
class _Interrupted(FakeBackend):
    """A backend that dies mid-Run — not an `Exception`, so it is not a per-Sample failure."""

    def transcribe(self, waveform: npt.NDArray[np.float32], language: Language) -> str:
        if self.calls:
            raise KeyboardInterrupt
        return super().transcribe(waveform, language)


def _record_lines(run_dir: Path) -> list[str]:
    return (run_dir / record.RECORD_NAME).read_text(encoding="utf-8").splitlines()


def _run_json(run_dir: Path) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(
        (run_dir / provenance.RUN_DESCRIPTOR_NAME).read_text(encoding="utf-8")
    )
    return document
