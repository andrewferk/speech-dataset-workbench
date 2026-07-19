"""Where the image stage sits in the two commands (#31, ADR-0011).

`images/` is a **1:1 mirror of the Manifest**: exactly two PNGs per Recording, on every build, for
every Recording — not only the flagged ones, and with no lookup. `validate` renders nothing, and
these tests pin that as behavior rather than as a promise about the code.

The abort case matters as much as the success case. A render failure is a tool bug, not a property
of the data, so it aborts the build; and because a build lands as one atomic commit, an abort
anywhere leaves no `images/` at all. A partial `images/` would make a missing PNG
indistinguishable from one never rendered.
"""

from pathlib import Path

import pytest

from sdw import images
from sdw.cli import main
from sdw.errors import HardError
from tests import synth


def _data_in(root: Path, count: int) -> Path:
    """A `--data-in` of ``count`` distinct Recordings, each a decodable tone of its own length."""
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(count):
        name = f"r{index}.wav"
        synth.write_wav(
            root / name,
            freq_hz=300.0 + 50 * index,
            amp_dbfs=-18.0,
            duration_s=0.5 + 0.1 * index,
            sample_rate=16000,
            bit_depth=16,
            channels=1,
        )
        rows.append({"path": name, "prompt_text": f"Line {index}."})
    synth.write_recordings_csv(root, rows)
    return root


def _build(data_in: Path, data_out: Path) -> int:
    return main(["build", "--data-in", str(data_in), "--data-out", str(data_out)])


class TestCoverage:
    def test_two_pngs_per_recording(self, tmp_path: Path) -> None:
        data_in, data_out = _data_in(tmp_path / "in", 3), tmp_path / "out"
        assert _build(data_in, data_out) == 0
        assert len(list((data_out / "images").iterdir())) == 6

    def test_every_recording_gets_both_images(self, tmp_path: Path) -> None:
        data_in, data_out = _data_in(tmp_path / "in", 3), tmp_path / "out"
        assert _build(data_in, data_out) == 0
        stems = {p.name.split(".")[0] for p in (data_out / "images").iterdir()}
        for stem in stems:
            assert (data_out / "images" / f"{stem}.waveform.png").is_file()
            assert (data_out / "images" / f"{stem}.spectrogram.png").is_file()

    def test_a_clean_recording_is_rendered_too(self, tmp_path: Path) -> None:
        # Coverage does not depend on the quality stage's verdicts: rendering only flagged
        # Recordings would make `images/` a function of `[quality]` thresholds (ADR-0011).
        data_in, data_out = _data_in(tmp_path / "in", 1), tmp_path / "out"
        assert _build(data_in, data_out) == 0
        assert len(list((data_out / "images").iterdir())) == 2


class TestValidateRendersNothing:
    def test_validate_writes_no_images_anywhere(self, tmp_path: Path) -> None:
        data_in = _data_in(tmp_path / "in", 2)
        before = sorted(p for p in tmp_path.rglob("*"))
        assert main(["validate", "--data-in", str(data_in)]) == 0
        assert sorted(p for p in tmp_path.rglob("*")) == before


class TestAbortLeavesNoImages:
    def test_an_undecodable_original_leaves_no_partial_images(self, tmp_path: Path) -> None:
        # The bad Original is the *last* row, so earlier Recordings have already rendered into the
        # staging tree when the abort fires. Nothing durable may survive it.
        data_in, data_out = _data_in(tmp_path / "in", 3), tmp_path / "out"
        synth.write_non_wav(data_in / "r2.wav")
        assert _build(data_in, data_out) != 0
        assert not data_out.exists()
        assert not data_out.with_name(data_out.name + ".tmp").exists()

    def test_a_render_failure_aborts_the_build(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The failure ADR-0011 legislates for directly: not a bad Original, but a render that
        # breaks. Warn-and-skip would leave a Recording with no PNG and the build exiting 0, which
        # is indistinguishable from one never rendered.
        data_in, data_out = _data_in(tmp_path / "in", 3), tmp_path / "out"
        calls = {"n": 0}

        def failing(*args: object, **kwargs: object) -> None:
            calls["n"] += 1
            if calls["n"] == 2:
                raise HardError("render exploded")

        monkeypatch.setattr(images, "render", failing)
        assert _build(data_in, data_out) != 0
        assert not data_out.exists()

    def test_a_previous_build_survives_an_abort(self, tmp_path: Path) -> None:
        data_in, data_out = _data_in(tmp_path / "in", 2), tmp_path / "out"
        assert _build(data_in, data_out) == 0
        good = {p.name: p.read_bytes() for p in (data_out / "images").iterdir()}

        broken = _data_in(tmp_path / "in2", 2)
        synth.write_non_wav(broken / "r1.wav")
        assert _build(broken, data_out) != 0
        assert {p.name: p.read_bytes() for p in (data_out / "images").iterdir()} == good


class TestRebuild:
    def test_a_rebuild_replaces_the_tree_and_is_byte_identical(self, tmp_path: Path) -> None:
        data_in, data_out = _data_in(tmp_path / "in", 2), tmp_path / "out"
        assert _build(data_in, data_out) == 0
        first = {p.name: p.read_bytes() for p in (data_out / "images").iterdir()}
        assert _build(data_in, data_out) == 0
        assert {p.name: p.read_bytes() for p in (data_out / "images").iterdir()} == first

    def test_a_stale_staging_tree_does_not_leak_into_the_build(self, tmp_path: Path) -> None:
        data_in, data_out = _data_in(tmp_path / "in", 1), tmp_path / "out"
        stale = data_out.with_name(data_out.name + ".tmp")
        (stale / "images").mkdir(parents=True)
        (stale / "images" / "rec_stale.waveform.png").write_bytes(b"junk")
        assert _build(data_in, data_out) == 0
        assert not (data_out / "images" / "rec_stale.waveform.png").exists()


@pytest.mark.parametrize("count", [1, 4])
def test_images_are_a_one_to_one_mirror_of_the_recordings(tmp_path: Path, count: int) -> None:
    data_in, data_out = _data_in(tmp_path / "in", count), tmp_path / "out"
    assert _build(data_in, data_out) == 0
    assert len(list((data_out / "images").iterdir())) == 2 * count
